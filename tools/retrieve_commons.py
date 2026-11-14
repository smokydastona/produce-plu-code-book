"""Acquire Commons candidates for rejected or all entries, without approving images."""
import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
import warnings
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from PIL import Image, ImageDraw, ImageOps

from license_register import write_register
from verify_images import LICENSES, validate
from check_image_uniqueness import image_fingerprint

API = "https://commons.wikimedia.org/w/api.php"
LAST_REQUEST = 0.0
TARGETS = {"3283": "Honeycrisp apple", "3016": "Concorde pear", "4555": "Savoy cabbage"}
QUERIES = {
    "9": "Honeycrisp apple", "27": "Concorde pear", "50": "white grapefruit",
    "148": "Passiflora ligularis", "154": "Julie mango", "175": "rambutan",
    "235": "sweet lime", "256": "white nectarine", "274": "Concorde pear",
    "334": "savoy cabbage", "344": "red carrot", "361": "white creamer potato",
    "368": "white creamer potato", "370": "yellow creamer potato",
    "373": "Japanese sweet potato", "391": "Anaheim pepper",
    "399": "Hungarian wax pepper", "403": "poblano pepper",
    "412": "poblano pepper", "415": "tomatillo", "424": "mini cucumber",
    "432": "golden acorn squash", "433": "white acorn squash",
    "457": "grey zucchini", "465": "napa cabbage", "466": "napa cabbage",
    "472": "napa cabbage", "475": "Luffa acutangula", "527": "red leaf lettuce",
    "570": "buttercup squash", "571": "butternut squash",
}


def plain(value):
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def fetch(url, user_agent):
    global LAST_REQUEST
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "commons.wikimedia.org", "upload.wikimedia.org"
    }:
        raise ValueError(f"unexpected Wikimedia URL: {url}")
    for attempt in range(4):
        time.sleep(max(0, 2 - (time.monotonic() - LAST_REQUEST)))
        LAST_REQUEST = time.monotonic()
        try:
            with urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=60) as response:
                data = response.read(50 * 1024 * 1024 + 1)
                if len(data) > 50 * 1024 * 1024:
                    raise ValueError("response exceeds 50 MiB")
                return data
        except HTTPError as exc:
            if exc.code not in {429, 503} or attempt == 3:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            delay = max(10 * (2 ** attempt), int(retry_after) if retry_after.isdigit() else 0)
            print(f"HTTP {exc.code}: waiting {delay}s before retry", file=sys.stderr)
            time.sleep(delay)


def search(product, user_agent, *, title=None):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f'{product} filetype:bitmap', "gsrnamespace": 6,
        "gsrlimit": 50, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    if title:
        params = {
            "action": "query", "format": "json", "titles": title,
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        }
    response = json.loads(fetch(API + "?" + urlencode(params), user_agent))
    if "error" in response:
        raise ValueError(f"Commons API error: {response['error']}")
    return sorted(response.get("query", {}).get("pages", {}).values(),
                  key=lambda page: page.get("index", 0))


def download(plu, product, output, user_agent, *, query=None,
             licenses=LICENSES, pages=None, used_images=None, rejections=None):
    if list(output.glob(f"{plu}.*")):
        raise FileExistsError(f"candidate already exists for PLU {plu}; will not overwrite")
    if used_images is None:
        used_images = {
            image_fingerprint(path): str(path)
            for path in output.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        }
    for page in search(query or product, user_agent) if pages is None else pages:
        info = page.get("imageinfo", [{}])[0]
        extra = info.get("extmetadata", {})
        get = lambda key: plain(extra.get(key, {}).get("value", ""))
        license_name = get("LicenseShortName")
        if license_name == "CC0 1.0":
            license_name = "CC0"
        if license_name not in licenses or get("Restrictions"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 500:
            continue
        suffix = {"image/jpeg": ".jpg", "image/png": ".png"}.get(info.get("mime"))
        if not suffix or not get("Artist"):
            continue
        if (Image.MAX_IMAGE_PIXELS is not None and
                info["width"] * info["height"] > Image.MAX_IMAGE_PIXELS):
            reason = f"{page.get('title', 'candidate')}: advertised dimensions exceed pixel safety limit"
            print(f"SKIP {plu}: {reason}", file=sys.stderr)
            if rejections is not None:
                rejections.append(reason)
            continue
        url = info["url"]
        content = fetch(url, user_agent)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if getattr(image, "n_frames", 1) != 1:
                        continue
                    image.load()
                    width, height = image.size
                fingerprint = image_fingerprint(io.BytesIO(content))
        except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
            reason = f"{page.get('title', 'candidate')}: unsafe or unreadable image: {exc}"
            print(f"SKIP {plu}: {reason}", file=sys.stderr)
            if rejections is not None:
                rejections.append(reason)
            continue
        if min(width, height) < 500:
            continue
        if fingerprint in used_images:
            print(f"SKIP {plu}: duplicate image already used by {used_images[fingerprint]}",
                  file=sys.stderr)
            continue
        path = output / f"{plu}{suffix}"
        sidecar = path.with_suffix(suffix + ".json")
        license_url = get("LicenseUrl")
        if not license_url and license_name == "Public domain":
            license_url = "https://creativecommons.org/publicdomain/mark/1.0/"
        if license_url.startswith("//"):
            license_url = "https:" + license_url
        if license_url.startswith("http://creativecommons.org/"):
            license_url = license_url.replace("http://", "https://", 1)
        if not license_url:
            continue
        metadata = {
            "plu": plu, "product": product, "creator": get("Artist"),
            "license": license_name, "license_url": license_url,
            "source_page_url": info["descriptionurl"], "original_image_url": url,
            "width": width, "height": height,
            "attribution": f"{get('Artist')} / {page['title']} / {license_name}",
            "approval_status": "CANDIDATE",
            "visual_verification": "NOT REVIEWED",
            "description": get("ImageDescription"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "commons_metadata": info,
        }
        output.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(content)
        with sidecar.open("x", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
            file.write("\n")
        errors = validate(path)
        if errors:
            raise ValueError(f"{path}: {'; '.join(errors)}")
        used_images[fingerprint] = str(path)
        print(f"Downloaded {path}; exact variety and photographic suitability NOT verified")
        return True
    print(f"UNRESOLVED {plu}: no eligible candidate for {product}", file=sys.stderr)
    return False


def rejected_entries(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = [row for row in csv.DictReader(file)
                if row["verdict"].lower() in {"r", "reject", "rejected"}]
    missing = {row["idx"] for row in rows} - QUERIES.keys()
    if missing:
        raise ValueError(f"No exact-variety search configured for entries {sorted(missing)}")
    return rows


def review_rejection_entries(path, report, source_sha256, working_items):
    if report.get("source_sha256") != source_sha256:
        raise ValueError("image review was made against a different PickList; rebuild and review current identities")
    if report.get("source") != "sources/plu/PickList.xml":
        raise ValueError("image review does not identify the authoritative PickList source")
    active = {item["source_id"]: item for item in working_items if item.get("included")}
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    decisions = {}
    entries = []
    sequences = set()
    for row in rows:
        sequence = row.get("sequence", "")
        source_id = row.get("working_list_id", "")
        if not sequence.isdigit() or sequence in sequences:
            raise ValueError("image review has a missing or duplicate sequence")
        sequences.add(sequence)
        item = active.get(source_id)
        if item is None:
            raise ValueError(f"image review identity is no longer active: {source_id}")
        if (row.get("plu"), row.get("working_product"), row.get("source_identity_ids")) != (
                item["plu"], item["name"], ";".join(item.get("source_ids", []))):
            raise ValueError(f"image review identity changed since review: {source_id}")
        decision = row.get("visual_decision", "")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision == "REJECTED":
            entries.append(dict(idx=sequence, plu=item["plu"], name=item["name"], source_id=source_id))
    if len(rows) != report.get("reviewed_working_list_entries") or decisions != report.get("decision_counts"):
        raise ValueError("image review CSV does not match its summary")
    if len(entries) != report.get("decision_counts", {}).get("REJECTED", 0):
        raise ValueError("image review rejected-entry count does not match its summary")
    if not entries:
        raise ValueError("image review contains no rejected entries to search")
    return entries


def current_review_rejections(root, review_path):
    from working_list import read_working_list

    report_path = review_path.with_suffix(".json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    source_path = root / "sources/plu/PickList.xml"
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    working_items, working_sha256 = read_working_list(root)
    if working_sha256 != source_sha256:
        raise ValueError("WorkingList reconciliation uses a different PickList version")
    return review_rejection_entries(review_path, report, source_sha256, working_items)


def select_review_sequence(entries, sequence):
    if not sequence:
        return entries
    if not sequence.isascii() or not sequence.isdecimal():
        raise ValueError("review sequence must be a positive decimal number")
    selected = [entry for entry in entries if entry["idx"] == sequence]
    if len(selected) != 1:
        raise ValueError(f"review sequence {sequence} is not a rejected current WorkingList entry")
    return selected


def apply_search_query(entries, search_query):
    if not search_query:
        return entries
    query = " ".join(search_query.split())
    if not query:
        raise ValueError("search query must not be blank")
    if len(entries) != 1:
        raise ValueError("search query override requires exactly one selected entry")
    return [dict(entries[0], query=query)]


def entry_query(entry):
    if entry.get("query"):
        return entry["query"]
    if not entry.get("source_id") and entry["idx"] in QUERIES:
        return QUERIES[entry["idx"]]
    query = re.sub(r"\b(organic|small|large|medium)\b", "", entry["name"], flags=re.I)
    query = re.sub(r"\bapples\b", "apple", query, flags=re.I)
    query = re.sub(r"\bpears\b", "pear", query, flags=re.I)
    query = re.sub(r"\btomatoes\b", "tomato", query, flags=re.I)
    query = re.sub(r"\bpeppers\b", "pepper", query, flags=re.I)
    query = " ".join(query.split())
    if not query:
        raise ValueError(f"entry {entry['idx']}: empty product search query")
    return query


def contact_sheets(records, output):
    for start in range(0, len(records), 12):
        sheet = Image.new("RGB", (1200, 1000), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, record in enumerate(records[start:start + 12]):
            x, y = (offset % 4) * 300, (offset // 4) * 320
            with Image.open(output / record["image"]) as image:
                thumbnail = ImageOps.exif_transpose(image).convert("RGB")
                thumbnail.thumbnail((280, 250))
                sheet.paste(thumbnail, (x, y))
            draw.text((x, y + 252), f"#{record['idx']} / PLU {record['plu']}", fill="black")
            draw.text((x, y + 270), record["product"][:38], fill="black")
            draw.text((x, y + 288), "UNREVIEWED - NOT APPROVED", fill="red")
        sheet.save(output / f"contact-sheet-{start // 12 + 1:02d}.jpg")


def acquire(entries, output, user_agent, limit, leads=()):
    if not entries:
        raise ValueError("review CSV selection contains no entries")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("review package output must be empty; originals will not be overwritten")
    report, records, queries, used_images = [], [], {}, {}
    for entry in entries:
        idx, plu, product = entry["idx"], entry["plu"], entry["name"]
        query = entry_query(entry)
        row = dict(idx=idx, plu=plu, product=product, query=query,
                   source="Wikimedia Commons", status="UNRESOLVED", details="", candidates=0)
        rejections = []
        try:
            from urllib.parse import unquote
            pages = []
            for lead in leads:
                if not entry.get("source_id") and lead["id"].lstrip("0") == idx:
                    title = unquote(urlparse(lead["source_page_url"]).path.removeprefix("/wiki/"))
                    pages.extend(search(query, user_agent, title=title))
            if query not in queries:
                queries[query] = search(query, user_agent)
            pages.extend(queries[query])
            seen = set()
            for number, page in enumerate(pages, 1):
                title = page.get("title")
                if title in seen:
                    continue
                seen.add(title)
                folder = output / "originals" / f"{int(idx):03d}" / str(number)
                if download(plu, product, folder, user_agent, query=query,
                            licenses=LICENSES, pages=[page], used_images=used_images,
                            rejections=rejections):
                    path = next(folder.glob("*.json"))
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    metadata.update(idx=idx, source_id=entry.get("source_id", ""), query=query,
                                    image=str(path.with_suffix("").relative_to(output)))
                    records.append(metadata)
                    row["candidates"] += 1
                    if row["candidates"] >= limit:
                        break
            if row["candidates"]:
                row["status"] = "CANDIDATES_ONLY"
            else:
                row["details"] = "No unique eligible licensed, sized candidate with creator metadata"
        except (OSError, ValueError, KeyError) as exc:
            row["status"] = "ERROR"
            row["details"] = str(exc)
            print(f"ERROR entry {idx}: {exc}", file=sys.stderr)
        if rejections:
            row["details"] = "; ".join(filter(None, [row["details"], *rejections]))
        report.append(row)
    (output / "provenance.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_register(records, output / "license-register.csv")
    with (output / "acquisition-report.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(report[0]) if report else
                                ["idx", "plu", "product", "query", "source", "status", "details", "candidates"])
        writer.writeheader()
        writer.writerows(report)
    contact_sheets(records, output)
    (output / "REVIEW.txt").write_text(
        "UNREVIEWED CANDIDATES - NOT APPROVED\n"
        "Search terms and Commons metadata do not establish variety, photographic origin, "
        "organic certification, or rights ownership.\n"
        "Review every entry independently, including shared PLUs. Check source pages, "
        "creator, licence, attribution, watermarks and exact variety before use.\n"
        "Each conventional entry requires a different photograph, even when PLUs repeat. "
        "Only matching conventional/organic products may reuse a photo, with the "
        "standard pink ORGANIC badge on every organic image. Candidates are kept "
        "distinct within this package; compare separate shards before assignment.\n"
        "Renaming, cropping or recolouring a reused image does not make it unique.\n"
        "Original files are unchanged; contact sheets are separate previews.\n"
        "No booklet or production register was modified.\n", encoding="utf-8")
    return any(row["status"] == "ERROR" for row in report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/images/candidates"))
    parser.add_argument("--user-agent", required=True,
                        help="Descriptive Wikimedia User-Agent including a contact URL/email")
    parser.add_argument("--review", type=Path,
                        help="Review CSV: acquire all rejected entries with supported reuse licences")
    parser.add_argument("--working-list-review", type=Path,
                        help="Identity-pinned IMAGE_VISUAL_REVIEW.csv; search only rejected current entries")
    parser.add_argument("--sequence", default="",
                        help="Limit --working-list-review to one review sequence")
    parser.add_argument("--search-query", default="",
                        help="Override Commons search terms for one selected review sequence")
    parser.add_argument("--all-entries", action="store_true",
                        help="Search every entry in --review, not only rejected images")
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based entry selection shard")
    parser.add_argument("--shard-count", type=int, default=1, help="Number of entry selection shards")
    parser.add_argument("--per-entry", type=int, default=2)
    parser.add_argument("--leads", type=Path,
                        help="Existing Commons URL manifest to try before search results")
    args = parser.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("--shard-index must be between 0 and --shard-count minus 1")
    if args.review and args.working_list_review:
        parser.error("--review and --working-list-review are mutually exclusive")
    if args.sequence and not args.working_list_review:
        parser.error("--sequence requires --working-list-review")
    if args.search_query and (not args.working_list_review or not args.sequence):
        parser.error("--search-query requires --working-list-review and --sequence")
    if not args.review and not args.working_list_review and (args.all_entries or args.shard_count != 1):
        parser.error("--all-entries and sharding require --review")
    if args.review or args.working_list_review:
        if not 1 <= args.per_entry <= 5:
            parser.error("--per-entry must be between 1 and 5")
        try:
            from candidate_manifest import read_manifest
            leads = read_manifest(args.leads) if args.leads else []
            if args.working_list_review:
                if args.all_entries:
                    parser.error("--all-entries cannot be combined with --working-list-review")
                entries = current_review_rejections(Path.cwd(), args.working_list_review)
                entries = select_review_sequence(entries, args.sequence)
                entries = apply_search_query(entries, args.search_query)
            elif args.all_entries:
                with args.review.open(newline="", encoding="utf-8-sig") as file:
                    entries = list(csv.DictReader(file))
            else:
                entries = rejected_entries(args.review)
            entries = entries[args.shard_index::args.shard_count]
            failed = acquire(entries, args.output, args.user_agent, args.per_entry, leads)
        except (OSError, ValueError, KeyError) as exc:
            parser.exit(1, f"ERROR: {exc}\n")
        raise SystemExit(1 if failed else 0)
    failed = False
    for plu, product in TARGETS.items():
        try:
            if not download(plu, product, args.output, args.user_agent):
                failed = True
        except (OSError, ValueError, KeyError) as exc:
            failed = True
            print(f"ERROR {plu}: {exc}", file=sys.stderr)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
