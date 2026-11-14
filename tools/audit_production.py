"""Audit legacy approvals and current release blockers without altering source evidence."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

from check_image_uniqueness import audit_entries
from organic_watermarks import is_organic, read_csv, verify_booklets
from sync_picklist import reconcile as reconcile_picklist

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
        owner_permission = metadata.get("rights_status") == "OWNER_CONFIRMED_PERMISSION"
        required = ["creator", "attribution"]
        if owner_permission:
            required.extend(("source_reference", "rights_evidence"))
            if metadata.get("license") != "OWNER_CONFIRMED_PERMISSION":
                errors.append("OWNER_PERMISSION_MUST_NOT_CLAIM_PUBLIC_LICENCE")
        else:
            required.extend(("license", "source_page_url", "license_url"))
        for key in required:
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
            organic=is_organic(row), approval_status="APPROVED_LEGACY",
            approval_basis="OWNER_LEGACY_PREAPPROVED_POLICY",
            visual_verdict="APPROVED_LEGACY", historical_visual_verdict=review["verdict"],
            historical_findings="; ".join(errors), blockers="NONE",
        ))
    counts = Counter(error for row in result
                     for error in row["historical_findings"].split("; ") if error)
    summary = dict(
        status="ALL_LEGACY_ENTRIES_APPROVED",
        entries=len(rows), organic_entries=sum(is_organic(row) for row in rows),
        prohibited_duplicate_groups=len(groups),
        entries_with_blockers=0, historical_finding_counts=dict(sorted(counts.items())),
        approval_basis="Owner policy: all legacy entries are pre-approved. Original visual verdicts, "
                       "technical findings and provenance remain recorded as historical evidence.",
        scope="Legacy image approval only. Non-produce remains a code-only supplement.",
    )
    return result, summary


def combined_summary(picklist_summary, image_summary=None):
    status = (
        "BLOCKED"
        if picklist_summary["status"] != "READY_TO_BUILD"
        else "AUTOMATED_CHECKS_PASSED_REQUIRES_RELEASE_REVIEW"
    )
    result = dict(
        status=status, picklist_sync=picklist_summary,
        scope="Current WorkingList reconciliation and image readiness. "
              "Final source, licence, variety and print-layout review is mandatory.",
    )
    if image_summary is not None:
        result["legacy_image_audit"] = image_summary
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="Report directory")
    parser.add_argument("--legacy", action="store_true",
                        help="Also inventory historical booklet images; not a production gate")
    args = parser.parse_args()
    try:
        output = args.output or args.root / "current/reports"
        output.mkdir(parents=True, exist_ok=True)
        _, _, _, picklist_summary = reconcile_picklist(args.root, output)
        if hashlib.sha256((args.root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != picklist_summary["source_sha256"]:
            raise ValueError("source changed during reconciliation; discard output and retry")
        image_summary = None
        if args.legacy:
            rows, image_summary = inventory(args.root)
            with (output / "PRODUCTION_BLOCKERS.csv").open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
        if hashlib.sha256((args.root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != picklist_summary["source_sha256"]:
            raise ValueError("source changed during audit; discard output and retry")
        summary = combined_summary(picklist_summary, image_summary)
        (output / "PRODUCTION_READINESS.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps(summary, indent=2))
    raise SystemExit(1 if summary["status"] == "BLOCKED" else 0)


if __name__ == "__main__":
    main()
