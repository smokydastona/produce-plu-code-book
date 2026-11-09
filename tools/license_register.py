"""Record candidate licence declarations, without granting rights or visual approval."""
import argparse
import csv
import html
import json
import re
from pathlib import Path

from verify_images import LICENSES

FIELDS = (
    "idx", "plu", "product", "image", "sha256", "width", "height",
    "source_page_url", "original_image_url", "creator", "license",
    "license_version", "license_url", "license_eligibility",
    "commercial_use", "modifications", "attribution_required", "attribution",
    "share_alike", "permission_notes", "restrictions",
    "rights_verification_status", "visual_approval_status",
)


def plain(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", value)).split())


def register_row(record):
    for key in ("idx", "plu", "product", "image", "creator", "license",
                "license_url", "source_page_url", "original_image_url"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f"candidate requires a nonempty string: {key}")
    name = record["license"]
    extra = record.get("commons_metadata", {}).get("extmetadata", {})
    get = lambda key: plain(extra.get(key, {}).get("value", ""))
    restrictions = get("Restrictions")
    eligible = name in LICENSES and not restrictions
    pd = name == "Public domain"
    credit = get("Attribution") or record.get("attribution") or record["creator"]
    attribution = (
        f"{credit}; {record['source_page_url']}; {name}: {record['license_url']}"
    )
    row = {key: record.get(key, "") for key in FIELDS}
    row.update(
        license_version=("1.0" if name == "CC0" else
                         name.rsplit(" ", 1)[-1] if name.startswith("CC BY") else ""),
        license_eligibility=("REQUIRES_REVIEW" if not eligible else
                             "CONDITIONAL_PUBLIC_DOMAIN" if pd else "ACCEPTED_TYPE"),
        commercial_use=("PERMITTED_IF_DECLARATION_VALID" if eligible and not pd
                        else "UNVERIFIED"),
        modifications=("PERMITTED_IF_DECLARATION_VALID" if eligible and not pd
                       else "UNVERIFIED"),
        attribution_required=("YES" if name.startswith("CC BY") else
                              "NO_COPYRIGHT_REQUIREMENT" if name == "CC0"
                              else "UNVERIFIED"),
        attribution=attribution,
        share_alike=("ADAPTATIONS_ONLY" if name.startswith("CC BY-SA") else
                     "NO" if eligible and not pd else "UNVERIFIED"),
        permission_notes=get("Permission"),
        restrictions=restrictions,
        rights_verification_status="NOT_VERIFIED",
        visual_approval_status="NOT_APPROVED",
    )
    return row


def write_register(records, destination):
    rows = [register_row(record) for record in records]
    with destination.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provenance", type=Path, help="Acquisition package provenance.json")
    parser.add_argument("--output", type=Path, required=True, help="New CSV; never overwrites a register")
    args = parser.parse_args()
    try:
        records = json.loads(args.provenance.read_text(encoding="utf-8"))
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise ValueError("provenance must be an array of candidate records")
        write_register(records, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
