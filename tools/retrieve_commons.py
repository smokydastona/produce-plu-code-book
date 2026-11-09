"""Acquire Commons candidates for rejected entries, without approving booklet images."""
import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from PIL import Image, ImageDraw, ImageOps

from license_register import write_register
from verify_images import LICENSES, validate

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
        "gsrsearch": f'"{product}" filetype:bitmap', "gsrnamespace": 6,
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
             licenses=LICENSES, pages=None):
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
        url = info["url"]
        content = fetch(url, user_agent)
        with Image.open(io.BytesIO(content)) as image:
            if getattr(image, "n_frames", 1) != 1:
                continue
            image.load()
            width, height = image.size
        if min(width, height) < 500:
            continue
        path = output / f"{plu}{suffix}"
        sidecar = path.with_suffix(suffix + ".json")
        if list(output.glob(f"{plu}.*")):
            raise FileExistsError(f"candidate already exists for PLU {plu}; will not overwrite")
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
        raise ValueError("review CSV contains no rejected entries")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("review package output must be empty; originals will not be overwritten")
    report, records, queries = [], [], {}
    for entry in entries:
        idx, plu, product = entry["idx"], entry["plu"], entry["name"]
        row = dict(idx=idx, plu=plu, product=product, query=QUERIES[idx],
                   source="Wikimedia Commons", status="UNRESOLVED", details="", candidates=0)
        try:
            from urllib.parse import unquote
            pages = []
            for lead in leads:
                if lead["id"].lstrip("0") == idx:
                    title = unquote(urlparse(lead["source_page_url"]).path.removeprefix("/wiki/"))
                    pages.extend(search(QUERIES[idx], user_agent, title=title))
            if QUERIES[idx] not in queries:
                queries[QUERIES[idx]] = search(QUERIES[idx], user_agent)
            pages.extend(queries[QUERIES[idx]])
            seen = set()
            for number, page in enumerate(pages, 1):
                title = page.get("title")
                if title in seen:
                    continue
                seen.add(title)
                folder = output / "originals" / f"{int(idx):03d}" / str(number)
                if download(plu, product, folder, user_agent, query=QUERIES[idx],
                            licenses=LICENSES, pages=[page]):
                    path = next(folder.glob("*.json"))
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                    metadata.update(idx=idx, query=QUERIES[idx],
                                    image=str(path.with_suffix("").relative_to(output)))
                    records.append(metadata)
                    row["candidates"] += 1
                    if row["candidates"] >= limit:
                        break
            if row["candidates"]:
                row["status"] = "CANDIDATES_ONLY"
            else:
                row["details"] = "No eligible licensed, sized candidate with creator metadata"
        except (OSError, ValueError, KeyError) as exc:
            row["status"] = "ERROR"
            row["details"] = str(exc)
            print(f"ERROR entry {idx}: {exc}", file=sys.stderr)
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
    parser.add_argument("--per-entry", type=int, default=2)
    parser.add_argument("--leads", type=Path,
                        help="Existing Commons URL manifest to try before search results")
    args = parser.parse_args()
    if args.review:
        if not 1 <= args.per_entry <= 5:
            parser.error("--per-entry must be between 1 and 5")
        try:
            from candidate_manifest import read_manifest
            leads = read_manifest(args.leads) if args.leads else []
            failed = acquire(rejected_entries(args.review), args.output,
                             args.user_agent, args.per_entry, leads)
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
