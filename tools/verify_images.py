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
OWNER_PERMISSION = "OWNER_CONFIRMED_PERMISSION"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif",
              ".bmp", ".avif", ".svg"}


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
    owner_permission = False
    try:
        metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text())
    except (OSError, ValueError) as exc:
        return errors + [f"missing or invalid provenance JSON: {exc}"]
    if not isinstance(metadata, dict):
        return errors + ["provenance JSON must be an object"]
    owner_permission = metadata.get("rights_status") == OWNER_PERMISSION
    required = ["plu", "product", "creator", "attribution"]
    if owner_permission:
        required.extend(("source_reference", "rights_evidence", "photographic_origin_evidence",
                         "visual_approval_evidence"))
        if metadata.get("license") != OWNER_PERMISSION:
            errors.append("owner permission must not be presented as a public licence")
        if metadata.get("photographic_origin") != "OWNER_CONFIRMED_PHOTO":
            errors.append("owner-provided image photographic origin is not confirmed")
    else:
        required.extend(("license", "source_page_url", "original_image_url", "license_url"))
    for key in required:
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            errors.append(f"missing/non-string metadata: {key}")
    for key in ("source_page_url", "original_image_url", "license_url"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            try:
                url = urlparse(value)
                valid_url = url.scheme == "https" and bool(url.hostname)
            except ValueError:
                valid_url = False
            if not valid_url:
                errors.append(f"{key} must be an absolute HTTPS URL")
    if not owner_permission and metadata.get("license") not in LICENSES:
        errors.append("licence is not a supported commercial-use licence")
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


def approved_library_pair(group, root):
    library = (root / "sources/image-library").resolve()
    copies = [path for path in group if path.parent == library]
    if len(group) != 2 or len(copies) != 1:
        return False
    from build_image_library import check_library, library_records

    check_library(root)
    records = {row["image"]: row for row in library_records(library)}
    record = records.get(copies[0].name)
    other = next(path for path in group if path != copies[0])
    return bool(record and (root / record["assigned_image"]).resolve() == other)


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
    library_paths = {path.resolve() for path in paths
                     if path.resolve().parent == Path("sources/image-library").resolve()}
    if library_paths:
        from build_image_library import check_library

        try:
            check_library(Path.cwd())
        except (OSError, ValueError, KeyError) as exc:
            failed = True
            print(f"FAIL image library verification: {exc}")
            library_paths = set()
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
        # A regenerated audit library may retain legacy reuse warnings without
        # authorizing new reuse among the assigned originals.
        group = group - library_paths
        if len(group) > 1 and group & changed and not group <= organic_paths:
            try:
                if approved_library_pair(group, Path.cwd()):
                    continue
            except (OSError, ValueError, KeyError) as exc:
                print(f"FAIL image library verification: {exc}")
            failed = True
            print("FAIL duplicate image content: " + ", ".join(str(path) for path in sorted(group)))
    for path in sorted(set(paths)):
        if path.resolve() in library_paths:
            print(f"PASS {path} (regenerated visual-reference library; "
                  "production limitations remain in its index and sidecar)")
            continue
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
