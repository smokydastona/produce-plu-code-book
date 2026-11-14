"""Validate candidate image files and their adjacent .json provenance records."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import warnings
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from check_image_uniqueness import audit_entries, image_fingerprint
from organic_watermarks import (is_organic, read_records, verified_original,
                                render_watermark, verify_booklets, badge_artwork)

PUBLIC_DOMAIN = {"CC0", "Public domain"}
LICENSES = PUBLIC_DOMAIN | {"CC BY 2.0", "CC BY 3.0", "CC BY 4.0",
                            "CC BY-SA 2.0", "CC BY-SA 3.0", "CC BY-SA 4.0"}
OWNER_CONFIRMED_PERMISSION_ASSETS = {
    ("aa097e83f41a5a55b85d443f14cebb150d36a318feaf94c0fdeaffea1cebf2d9",
     "4055", "Murcott Tangerines",
     "09df42d831061953e2d95b5f3e2071ef7f26a68b008377ecb6ce871b0b546186"),
    ("57e11bf34fbcbb165bda477a1ffd366ad23d482df185872fa7cd1612f064b012",
     "4552", "Napa Cabbage",
     "074b0d50fb0eb911404fbe4dc12ab58c6b40d3b7a135ef9a1a8c7f967819a740"),
    ("7b7ecf98feeff7e3efd7f636d69dded824fb7d70c399608ac56284bd771ba33e",
     "4253", "Strawberries by the Flat",
     "831477f2fab34a6c4c61d3462e135ee1da505cd870459c90f8258a057fd59ebb"),
    ("f42ed4640a1fdee6a371d45494e810d3231e53997c217458aafd4debddee9af6",
     "4885", "Basil",
     "c14af7546903339dbb6cffef40aa7e283bb28919139912d49a2d5311fb74be76"),
    ("58e6af2c6946076a9375ec1c8424364eb3e99c8ad4e2117fd0035771533dd38b",
     "4889", "Cilantro",
     "60ca8b961bca92e700d048723f1f57038be5e60377d6b96532761abc7048e883"),
    ("211ce953f2a57e0f1c217fd7c6c2db5b14665f10f322dfbdcc38d2791133c565",
     "4458", "Tangerine Seedless",
     "f05f37d3982f0277cb7d7eb67ca44a0993c264f8dbb30f8f98dd658ddd80ad5a"),
    ("b50be3217c32e08d35ac39824c83a39617c83f6519a31e6a2e5efbbcbc92e037",
     "4724", "White Creamer Potatoes",
     "4d1579b29ca61345f1ce202b9cbc37c8d37f3c4e014ac093dad497c29348cd7b"),
    ("0e90773e3a6c7f59866cec2e342659de0330b5a4ee76449e4203b72cb9523b6f",
     "4723", "Red Creamer Potatoes",
     "e715b10aaa4049d45fad378f21e196bfc305b8d1dc90b8ff46162d7bd632fafd"),
    ("37d199942d6fd74d002843f3820399b668608b933cda7a9791b2bb4ab24eb5d4",
     "4074", "Red-Fleshed Sweet Potato",
     "2ef9f5b01cd9e311877e44de695382686e1e4f162dca4e7a8f805c9966a341f4"),
    ("85a079aba7341916f6697a0605b4c98d350405d7d3485d657c7ff5c64c1acaab",
     "60271", "Early Nugget (Warba) Potatoes",
     "0396b0cf59795c2b5942fa41cbabd05263cafd3f66c15b8b20c5679d745e8eac"),
}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif",
              ".bmp", ".avif", ".svg"}


def owner_permission_metadata(metadata):
    identity = (metadata.get("sha256"), metadata.get("plu"), metadata.get("product"),
                metadata.get("working_list_id"))
    return (
        identity in OWNER_CONFIRMED_PERMISSION_ASSETS
        and metadata.get("license") == "OWNER_CONFIRMED_PERMISSION"
        and metadata.get("rights_verification_status") == "OWNER_CONFIRMED_PERMISSION"
        and isinstance(metadata.get("rights_evidence"), str)
        and bool(metadata["rights_evidence"].strip())
        and metadata.get("photographic_origin") == "VERIFIED_PHOTO"
        and metadata.get("visual_approval_status") == "APPROVED"
    )


def owner_permission_assignment(item, assignment):
    provenance = assignment.get("provenance", {})
    identity = (assignment.get("image_sha256"), item.get("plu"), item.get("name"),
                item.get("source_id"))
    return (
        identity in OWNER_CONFIRMED_PERMISSION_ASSETS
        and assignment.get("reviewed_plu") == item.get("plu")
        and assignment.get("reviewed_product") == item.get("name")
        and assignment.get("rights_verification_status") == "OWNER_CONFIRMED_PERMISSION"
        and assignment.get("production_status") ==
        "APPROVED_FOR_EXACT_WORKINGLIST_ASSIGNMENT"
        and assignment.get("photographic_origin") == "VERIFIED_PHOTO"
        and assignment.get("visual_approval_status") == "APPROVED"
        and provenance.get("license") == "OWNER_CONFIRMED_PERMISSION"
        and isinstance(provenance.get("rights_evidence"), str)
        and bool(provenance["rights_evidence"].strip())
    )


def validate(path):
    errors = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                size = image.size
                if min(size) < 500:
                    errors.append(f"shortest side is {min(size)} px; minimum is 500")
                if getattr(image, "n_frames", 1) != 1:
                    errors.append("animated/multiframe images are not supported")
                image.verify()
            with Image.open(path) as image:
                image.load()
    except (OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        return [f"invalid image: {exc}"]
    try:
        metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text())
    except (OSError, ValueError) as exc:
        return errors + [f"missing or invalid provenance JSON: {exc}"]
    if not isinstance(metadata, dict):
        return errors + ["provenance JSON must be an object"]
    owner_permission = owner_permission_metadata(metadata)
    required = ["plu", "product", "creator", "license", "attribution",
                "source_page_url", "original_image_url"]
    if not owner_permission:
        required.append("license_url")
    for key in required:
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            errors.append(f"missing/non-string metadata: {key}")
    for key in ("source_page_url", "original_image_url"):
        value = metadata.get(key)
        if isinstance(value, str):
            try:
                url = urlparse(value)
                valid_url = url.scheme == "https" and bool(url.hostname)
            except ValueError:
                valid_url = False
            if not valid_url:
                errors.append(f"{key} must be an absolute HTTPS URL")
    if metadata.get("license") in LICENSES:
        license_url = metadata.get("license_url")
        try:
            parsed = urlparse(license_url)
            valid_license_url = parsed.scheme == "https" and bool(parsed.hostname)
        except (TypeError, ValueError):
            valid_license_url = False
        if not valid_license_url:
            errors.append("license_url must be an absolute HTTPS URL")
    elif not owner_permission:
        errors.append("licence is not a supported commercial-use licence")
    elif metadata.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        errors.append("owner-confirmed permission requires a matching recorded checksum")
    if metadata.get("width") != size[0] or metadata.get("height") != size[1]:
        errors.append("recorded dimensions do not match the file")
    if metadata.get("approval_status") != "CANDIDATE":
        errors.append("approval_status must be CANDIDATE; automated checks do not approve photos")
    return errors


def baseline_assignments(base):
    def content(path):
        return subprocess.check_output(["git", "show", f"{base}:{path}"])

    rows = list(csv.DictReader(io.StringIO(content("data/entries.csv").decode("utf-8-sig"))))
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{base}:data/organic_watermarks.json"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    records = ({r["idx"]: r for r in json.loads(content("data/organic_watermarks.json"))}
               if exists.returncode == 0 else {})
    sources, originals, fingerprints = {}, {}, {}
    for row in rows:
        image = content("data/" + row["image"])
        originals[row["idx"]] = image
        record = records.get(row["idx"])
        if record:
            source = record["source_document"]
            if source not in sources:
                sources[source] = content(source)
            with zipfile.ZipFile(io.BytesIO(sources[source])) as archive:
                image = archive.read(record["source_member"])
        fingerprints[row["idx"]] = image_fingerprint(io.BytesIO(image))
    groups = audit_entries(rows, Path("data"), check_watermarks=False,
                           fingerprint_for=lambda row: fingerprints[row["idx"]])
    return rows, originals, groups, fingerprints


def check_assignment_changes(base):
    with Path("data/entries.csv").open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError("entry CSV is empty")
    verify_booklets(Path("."), rows)
    if Path("data/branding/pink-organic-badge.png").read_bytes() != badge_artwork():
        raise ValueError("organic badge artwork differs from the standard design")
    current = audit_entries(rows, Path("data"))
    old_rows, old_images, old_groups, old_fingerprints = baseline_assignments(base)
    old_sets = [{row["idx"] for row in group} for group in old_groups]
    old_by_idx = {row["idx"]: row for row in old_rows}
    records = read_records(Path("data"))
    for group in current:
        ids = {row["idx"] for row in group}
        unchanged = True
        for row in group:
            old = old_by_idx.get(row["idx"])
            if old is None or any(old[key] != row[key] for key in ("book", "plu", "name")):
                unchanged = False
                break
            original = (io.BytesIO(verified_original(row, records.get(row["idx"]), Path("data")))
                        if is_organic(row) else Path("data") / row["image"])
            if image_fingerprint(original) != old_fingerprints[row["idx"]]:
                unchanged = False
                break
        if not unchanged or not any(ids <= old for old in old_sets):
            raise ValueError("new prohibited image reuse at entries " + ", ".join(sorted(ids)))
    if current:
        print(f"WARN {len(current)} pre-existing prohibited image groups still need replacement")
    legacy_watermarks = set()
    organic_paths = set()
    for row in rows:
        if not is_organic(row):
            continue
        content = verified_original(row, records.get(row["idx"]), Path("data"))
        path = (Path("data") / row["image"]).resolve()
        organic_paths.add(path)
        old = old_by_idx.get(row["idx"])
        if old is not None and all(old[key] == row[key] for key in ("book", "plu", "name")):
            previous = old_images[row["idx"]]
            if (hashlib.sha256(previous).digest() == hashlib.sha256(content).digest() or
                    image_fingerprint(io.BytesIO(previous)) ==
                    image_fingerprint(io.BytesIO(render_watermark(content)))):
                legacy_watermarks.add(path)
    return organic_paths, legacy_watermarks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path)
    parser.add_argument("--changed-from", help="Git base commit; check added/modified images only")
    args = parser.parse_args()
    paths = args.images
    entries_changed = False
    if args.changed_from:
        base = subprocess.check_output([
            "git", "merge-base", args.changed_from, "HEAD",
        ]).decode().strip()
        names = subprocess.check_output([
            "git", "diff", "--name-only", "-z", "--diff-filter=AMRD",
            base, "HEAD", "--", "data/images", "data/entries.csv",
            "data/organic_watermarks.json", "data/branding", "sources", "current/booklets",
        ]).decode().split("\0")
        for name in filter(None, names):
            if name in {"data/entries.csv", "data/organic_watermarks.json"}:
                entries_changed = True
            if name.startswith("data/branding/"):
                entries_changed = True
                continue
            if name.startswith("current/booklets/") and name.endswith(".docx"):
                entries_changed = True
            path = Path(name)
            if path.suffix.lower() == ".json":
                path = path.with_suffix("")
            if path.suffix.lower() in EXTENSIONS and path.is_file():
                paths.append(path)
    failed = False
    organic_paths, legacy_watermarks = set(), set()
    if args.changed_from and (entries_changed or paths):
        try:
            organic_paths, legacy_watermarks = check_assignment_changes(base)
        except (OSError, ValueError, KeyError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            failed = True
            print(f"FAIL entry image assignments: {exc}")
    paths = sorted(set(paths))
    changed = {path.resolve() for path in paths}
    fingerprints = {}
    comparison_paths = set(paths)
    for root in (Path("data/images"), Path("sources")) if paths else ():
        if root.is_dir():
            comparison_paths.update(path for path in root.rglob("*")
                                    if path.is_file() and path.suffix.lower() in EXTENSIONS)
    for path in sorted(comparison_paths):
        try:
            fingerprint = image_fingerprint(path)
        except (OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            failed = True
            print(f"FAIL {path}: cannot check image uniqueness: {exc}")
            continue
        fingerprints.setdefault(fingerprint, set()).add(path.resolve())
    for group in fingerprints.values():
        if len(group) > 1 and group & changed and not group <= organic_paths:
            failed = True
            print("FAIL duplicate image content: " + ", ".join(str(path) for path in sorted(group)))
    for path in sorted(set(paths)):
        if path.resolve() in legacy_watermarks:
            print(f"WARN {path}: verified watermark-only update of a legacy image; "
                  "existing size, licence and visual-review limitations remain")
            continue
        errors = validate(path)
        if errors:
            failed = True
            print(f"FAIL {path}: {'; '.join(errors)}")
        else:
            print(f"PASS {path} (technical checks only; visual review still required)")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
