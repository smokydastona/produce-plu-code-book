"""Audit entry images for reuse; duplicate or missing images fail the check."""
import argparse
import csv
import hashlib
import io
import warnings
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageOps
from organic_watermarks import is_organic, read_records, verified_original

ROOT = Path(__file__).resolve().parents[1]


def image_fingerprint(path):
    """Compare decoded, oriented pixels rather than filenames or file metadata."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError(f"{path}: multiframe images are not supported")
            pixels = ImageOps.exif_transpose(image).convert("RGBA")
            digest = hashlib.sha256()
            digest.update(f"{pixels.width}x{pixels.height}:RGBA:".encode("ascii"))
            digest.update(pixels.tobytes())
            return digest.hexdigest()


def allowed_organic_pair(group):
    conventional = [row for row in group if not is_organic(row)]
    return (len(conventional) == 1 and
            all(row["book"] == conventional[0]["book"] and
                row["plu"] == "9" + conventional[0]["plu"]
                for row in group if is_organic(row)))


def audit_entries(rows, image_root, check_watermarks=True, fingerprint_for=None):
    groups = defaultdict(list)
    seen = set()
    records = read_records(image_root) if check_watermarks else {}
    for row in rows:
        idx = row["idx"]
        if not idx or idx in seen:
            raise ValueError(f"missing or repeated entry ID: {idx!r}")
        seen.add(idx)
        if not row["image"]:
            raise ValueError(f"entry {idx} / PLU {row['plu']}: missing image assignment")
        if fingerprint_for is not None:
            fingerprint = fingerprint_for(row)
        elif check_watermarks and is_organic(row):
            content = verified_original(row, records.get(idx), image_root)
            fingerprint = image_fingerprint(io.BytesIO(content))
        else:
            fingerprint = image_fingerprint(image_root / row["image"])
        groups[fingerprint].append(row)
    return [group for group in groups.values()
            if len(group) > 1 and not allowed_organic_pair(group)]


def require_unique_entries(rows, image_root):
    groups = audit_entries(rows, image_root)
    if groups:
        entries = sum(map(len, groups))
        raise ValueError(
            f"{entries} entries share images in {len(groups)} prohibited groups; "
            "only a matching conventional/organic pair with the standard pink "
            "ORGANIC watermark may reuse a photo. Run "
            "python3 tools/check_image_uniqueness.py --report "
            "outputs/reports/DUPLICATE_IMAGE_REPORT.csv for details."
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=Path, default=ROOT / "data/entries.csv")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        with args.entries.open(newline="", encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file))
        if not rows:
            raise ValueError("entry CSV is empty")
        groups = audit_entries(rows, args.entries.parent)
        if args.report:
            with args.report.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=[
                    "group", "idx", "book", "plu", "name", "image", "shared_entries",
                ])
                writer.writeheader()
                for number, group in enumerate(groups, 1):
                    for row in group:
                        writer.writerow(dict(
                            group=number, shared_entries=len(group),
                            **{key: row[key] for key in ("idx", "book", "plu", "name", "image")},
                        ))
    except (OSError, ValueError, KeyError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    count = sum(map(len, groups))
    print(f"{len(rows)} entries; {len(groups)} prohibited duplicate groups; "
          f"{count} affected entries")
    raise SystemExit(1 if groups else 0)


if __name__ == "__main__":
    main()
