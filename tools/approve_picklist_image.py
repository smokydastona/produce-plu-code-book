"""Record an explicit, evidence-backed image review; never modify PickList.xml."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path

from check_image_uniqueness import image_fingerprint
from picklist_catalog import read_assignments
from sync_picklist import organic, original_image
from verify_images import OWNER_PERMISSION, validate
from working_list import read_working_list

ROOT = Path(__file__).resolve().parents[1]


def approve(root, source_id, candidate, book, section, source_sha, evidence,
            reuse_from="", replace=False):
    items, digest = read_working_list(root)
    if digest != source_sha:
        raise ValueError("PickList changed since review; rerun WorkingList reconciliation and review the current source")
    included = {item["source_id"]: item for item in items if item["included"]}
    if source_id not in included:
        raise ValueError("source_id is not an included WorkingList entry")
    item = included[source_id]
    registry = root / "data/picklist_assignments.json"
    assignments = read_assignments(registry)
    if source_id in assignments and not replace:
        raise ValueError("assignment exists; explicitly use --replace after reviewing the replacement")
    if book not in {"Fruit", "Vegetable", "Non-produce"} or not section.strip() or not evidence.strip():
        raise ValueError("book, section and independent rights evidence are required")
    errors = validate(candidate)
    if errors:
        raise ValueError("; ".join(errors))
    metadata = json.loads(candidate.with_suffix(candidate.suffix + ".json").read_text(encoding="utf-8"))
    content = candidate.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    if metadata.get("sha256") != checksum:
        raise ValueError("candidate checksum does not match captured provenance")
    if (metadata.get("plu"), metadata.get("product")) != (item["plu"], item["name"]):
        raise ValueError("candidate provenance does not identify this exact product and PLU")
    owner_permission = metadata.get("rights_status") == OWNER_PERMISSION
    if owner_permission and metadata.get("rights_evidence") != evidence:
        raise ValueError("rights evidence must match the owner attestation in the candidate record")
    if reuse_from:
        if not organic(item) or reuse_from not in included or reuse_from not in assignments:
            raise ValueError("reuse requires an organic entry and an assigned current counterpart")
        counterpart = included[reuse_from]
        reference = assignments[reuse_from]
        if organic(counterpart) or reference["book"] != book:
            raise ValueError("reuse counterpart must be conventional and in the same booklet")
        if image_fingerprint(io.BytesIO(original_image(root, reference))) != image_fingerprint(io.BytesIO(content)):
            raise ValueError("reuse counterpart has a different original photograph")
    destination = root / "data/images/approved" / (checksum + candidate.suffix.lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != content:
        raise ValueError("destination exists with different content")
    if not destination.exists():
        shutil.copyfile(candidate, destination)
    approved_metadata = dict(
        metadata, visual_approval_status="APPROVED",
        rights_verification_status="VERIFIED",
    )
    sidecar = destination.with_suffix(destination.suffix + ".json")
    if not sidecar.exists():
        with sidecar.open("x", encoding="utf-8") as file:
            json.dump(approved_metadata, file, ensure_ascii=False, indent=2)
            file.write("\n")
    provenance = {key: metadata.get(key, "") for key in
                  ("creator", "license", "license_url", "source_page_url",
                   "original_image_url", "source_reference", "rights_status",
                   "photographic_origin_evidence", "visual_approval_evidence", "attribution")}
    provenance.update(changes="Original uploaded image bytes unchanged", rights_evidence=evidence)
    assignments[source_id] = dict(
        source_id=source_id, book=book, section=section, image=str(destination.relative_to(root)),
        image_mode="PHOTO", reviewed_plu=item["plu"], reviewed_product=item["name"],
        working_source_ids=item["source_ids"], working_decision_id=item["decision_id"],
        image_sha256=checksum, photographic_origin="VERIFIED_PHOTO",
        visual_approval_status="APPROVED", rights_verification_status="VERIFIED",
        provenance=provenance, reuse_from_source_id=reuse_from,
    )
    saved = json.loads(registry.read_text(encoding="utf-8"))
    saved["assignments"] = list(assignments.values())
    if hashlib.sha256((root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != source_sha:
        raise ValueError("PickList changed during review; assignment was not saved")
    temporary = registry.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8") as file:
        json.dump(saved, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary.replace(registry)
    from build_image_library import refresh_library

    try:
        library = refresh_library(root)
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"image approval was saved, but library refresh failed: {exc}") from exc
    if book in {"Fruit", "Vegetable"} and (
            source_id not in library["source_ids"]
            or source_id in library["blockers_by_source_id"]):
        blockers = library["blockers_by_source_id"].get(source_id, [])
        raise ValueError(
            "image approval was saved, but this entry remains blocked for production; "
            + (", ".join(blockers) if blockers else "check its current classification"))
    print(f"Recorded reviewed WorkingList image for {item['plu']} / {item['name']}; "
          "approved image library refreshed; full catalogue validation still required before publication")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--candidate", type=Path, required=True, help="Original plus adjacent provenance JSON")
    parser.add_argument("--book", choices=["Fruit", "Vegetable", "Non-produce"], required=True)
    parser.add_argument("--section", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--rights-evidence", required=True,
                        help="Evidence from source/rights review, including an owner attestation when applicable")
    parser.add_argument("--reuse-from", default="", help="Reviewed conventional counterpart source_id")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--approve-visual", action="store_true")
    parser.add_argument("--verify-photo", action="store_true")
    parser.add_argument("--verify-rights", action="store_true")
    args = parser.parse_args()
    if not all((args.approve_visual, args.verify_photo, args.verify_rights)):
        parser.error("explicit --approve-visual --verify-photo --verify-rights confirmations are required")
    try:
        approve(args.root, args.source_id, args.candidate, args.book, args.section,
                args.expected_source_sha, args.rights_evidence, args.reuse_from, args.replace)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
