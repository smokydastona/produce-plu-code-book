"""Write a release-blocker inventory; never grant visual or rights approval."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

from check_image_uniqueness import audit_entries
from organic_watermarks import is_organic, read_csv, verify_booklets

ROOT = Path(__file__).resolve().parents[1]


def image_blockers(row, review, root):
    path = root / "data" / row["image"]
    errors = []
    with Image.open(path) as image:
        image.load()
        width, height = ImageOps.exif_transpose(image).size
    if min(width, height) < 500:
        errors.append("BELOW_500_PX")
    if (str(width), str(height)) != (row["width"], row["height"]):
        errors.append("RECORDED_DIMENSIONS_MISMATCH")
    if review["verdict"] != "Approved":
        errors.append("VISUAL_" + review["verdict"].upper())
    if row["source"] == "AI Generated":
        errors.append("AI_REFERENCE_NOT_PHOTOGRAPH")
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.exists():
        errors.append("MISSING_IMAGE_PROVENANCE_AND_RIGHTS_VERIFICATION")
    else:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError(f"{sidecar}: expected an object")
        if metadata.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            errors.append("PROVENANCE_CHECKSUM_MISMATCH")
        if (metadata.get("plu"), metadata.get("product")) != (row["plu"], row["name"]):
            errors.append("PROVENANCE_ASSIGNMENT_MISMATCH")
        if metadata.get("rights_verification_status") != "VERIFIED":
            errors.append("IMAGE_RIGHTS_NOT_VERIFIED")
        if metadata.get("visual_approval_status") != "APPROVED":
            errors.append("IMAGE_VISUAL_APPROVAL_NOT_RECORDED")
        for key in ("creator", "license", "source_page_url", "license_url", "attribution"):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                errors.append("MISSING_PROVENANCE_" + key.upper())
    return width, height, errors


def inventory(root):
    rows = read_csv(root / "data/entries.csv")
    if not rows:
        raise ValueError("entry CSV is empty")
    reviews = read_csv(root / "data/image_review.csv")
    by_idx = {row["idx"]: row for row in reviews}
    if len(by_idx) != len(reviews) or set(by_idx) != {row["idx"] for row in rows}:
        raise ValueError("review and entry IDs must match exactly, without duplicates")
    verify_booklets(root, rows)
    groups = audit_entries(rows, root / "data")
    duplicate_ids = {row["idx"] for group in groups for row in group}
    result = []
    for row in rows:
        review = by_idx[row["idx"]]
        if any(row[key] != review[key] for key in ("book", "plu", "name", "image")):
            raise ValueError(f"entry {row['idx']}: review assignment mismatch")
        width, height, errors = image_blockers(row, review, root)
        if row["idx"] in duplicate_ids:
            errors.append("PROHIBITED_IMAGE_REUSE")
        result.append(dict(
            idx=row["idx"], book=row["book"], plu=row["plu"], product=row["name"],
            image="data/" + row["image"], width=width, height=height,
            organic=is_organic(row), visual_verdict=review["verdict"],
            blockers="; ".join(errors),
        ))
    counts = Counter(error for row in result for error in row["blockers"].split("; ") if error)
    summary = dict(
        status="BLOCKED" if counts else "AUTOMATED_CHECKS_PASSED_REQUIRES_RELEASE_REVIEW",
        entries=len(rows), organic_entries=sum(is_organic(row) for row in rows),
        prohibited_duplicate_groups=len(groups),
        entries_with_blockers=sum(bool(row["blockers"]) for row in result),
        blocker_counts=dict(sorted(counts.items())),
        scope="Fruit and vegetable image readiness only. Does not certify varieties, "
              "organic status, licences, source-code accuracy, or final print layout. "
              "Non-produce remains a code-only supplement; final release review is mandatory.",
    )
    return result, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="Existing report directory")
    args = parser.parse_args()
    try:
        rows, summary = inventory(args.root)
        output = args.output or args.root / "current/reports"
        with (output / "PRODUCTION_BLOCKERS.csv").open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        (output / "PRODUCTION_READINESS.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps(summary, indent=2))
    raise SystemExit(1 if summary["entries_with_blockers"] else 0)


if __name__ == "__main__":
    main()
