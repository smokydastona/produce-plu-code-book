"""One-time migration of existing booklet associations under legacy pre-approval."""
import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict, deque
from pathlib import Path

from docx import Document

from organic_watermarks import original_content, read_records
from picklist_catalog import read_picklist

ROOT = Path(__file__).resolve().parents[1]


def initialize(root, output):
    with (root / "data/image_review.csv").open(newline="", encoding="utf-8-sig") as file:
        reviews = list(csv.DictReader(file))
    available = defaultdict(deque)
    records = read_records(root / "data")
    for row in reviews:
        assignment = dict(
            book=row["book"], section=row["section"], image="data/" + row["image"],
            image_mode="PHOTO", reviewed_plu=row["plu"], reviewed_product=row["name"],
            visual_approval_status="APPROVED",
            image_approval_basis="OWNER_LEGACY_PREAPPROVED_POLICY",
            photographic_origin="NOT_VERIFIED", rights_verification_status="NOT_VERIFIED",
            provenance={}, legacy_entry_idx=row["idx"],
            migration_note=("Legacy image pre-approved by owner policy; original verdict and "
                            "unverified source/rights status remain historical evidence."),
        )
        record = records.get(row["idx"])
        if record:
            assignment["legacy_organic_original"] = {
                key: record[key] for key in ("source_document", "source_member", "original_sha256")}
            content = original_content(record, root)
        else:
            content = (root / "data" / row["image"]).read_bytes()
        assignment["image_sha256"] = hashlib.sha256(content).hexdigest()
        available[(row["plu"], row["name"])].append(assignment)
    for table in Document(root / "current/booklets/NON_PRODUCE_PLU_CASHIER_BOOKLET.docx").tables:
        for row in table.rows:
            for cell in row.cells:
                match = re.search(
                    r"^(.*?)\nPICKLIST CODE\s+(\S+)\nCategory\s+(.*?)\n", cell.text, re.S)
                if match:
                    name, plu, section = match.groups()
                    available[(plu, name)].append(dict(
                        book="Non-produce", section=section, image="", image_mode="CODE_ONLY",
                        code_only_approved=True, reviewed_plu=plu, reviewed_product=name,
                        migration_note="Existing code-only non-produce scope retained.",
                    ))
    items, digest = read_picklist(root / "sources/plu/PickList.xml")
    assignments = []
    for item in items:
        if item["included"] and available[(item["plu"], item["name"])]:
            assignment = available[(item["plu"], item["name"])].popleft()
            assignment["source_id"] = item["source_id"]
            assignments.append(assignment)
    unmatched = sum(map(len, available.values()))
    if unmatched:
        raise ValueError(f"{unmatched} existing booklet records have no visible XML counterpart")
    with output.open("x", encoding="utf-8") as file:
        json.dump(dict(schema_version=1, initial_source_sha256=digest, assignments=assignments),
                  file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Migrated {len(assignments)} existing assignments; "
          f"{sum(item['included'] for item in items) - len(assignments)} XML records still need assignments")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "data/picklist_assignments.json")
    args = parser.parse_args()
    try:
        initialize(args.root, args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
