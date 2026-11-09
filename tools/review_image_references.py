"""Identity-linked review images; never grant production image approvals."""
import hashlib
import io
import json
from collections import defaultdict

from PIL import Image

from sync_picklist import safe_asset

MANIFESTS = (
    "data/review-references/additional-36-ai.json",
    "data/review-references/missing-ai.json",
    "data/review-references/corrected-five-ai.json",
)


def load_references(root, rows):
    references, audit = {}, []
    for name in MANIFESTS:
        selected, records = load_manifest(root, rows, root / name)
        if references.keys() & selected.keys():
            raise ValueError("multiple AI references for the same source identity")
        references.update(selected)
        audit.extend(records)
    supplier, records = load_supplier(root, rows)
    references.update(supplier)
    audit.extend(records)
    return references, audit


def load_supplier(root, rows):
    path = root / "data/review-references/buck-brand.json"
    if not path.exists():
        return {}, []
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1 or manifest["rights_status"] != "OWNER_CONFIRMED_PERMISSION":
        raise ValueError("supplier references require explicit owner-confirmed permission")
    if not manifest["rights_evidence"].strip() or not manifest["attribution"].strip():
        raise ValueError("supplier reference permission evidence and attribution are required")
    folder = "data/review-references/buck-brand/"
    inventory = json.loads(safe_asset(root, folder + "IMAGE_INVENTORY.json").read_text())
    assets = {row["filename"]: row for row in inventory}
    references, audit, seen = {}, [], set()
    for mapping in manifest["mappings"]:
        identity = (mapping["plu"], mapping["product"])
        if not all(isinstance(value, str) and value for value in identity) or identity in seen:
            raise ValueError("supplier references require unique exact string identities")
        seen.add(identity)
        matches = [row for row in rows if (row["plu"], row["name"]) == identity]
        asset = assets[mapping["asset"]]
        content = safe_asset(root, folder + mapping["asset"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != asset["sha256"]:
            raise ValueError("supplier reference checksum changed; fresh review required")
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.size != (asset["width"], asset["height"]):
                raise ValueError("supplier reference dimensions differ from extraction evidence")
            rendered = io.BytesIO()
            image.convert("RGB").save(rendered, format="PNG")
        record = dict(
            source_id=matches[0]["source_id"] if len(matches) == 1 else "",
            plu=identity[0], product=identity[1], decision="SUPPLIER_REFERENCE",
            status="SUPPLIER_REFERENCE" if len(matches) == 1 else
                   "NO_ACTIVE_EXACT_IDENTITY" if not matches else "AMBIGUOUS_DUPLICATE_IDENTITY",
            source_document=manifest["source_url"], source_sha256=manifest["pdf_sha256"],
            crop_box="", crop_sha256=asset["sha256"], width=asset["width"], height=asset["height"],
            source_member=mapping["asset"], image_source="Four Seasons Produce / Buck Brand",
            rights_status=manifest["rights_status"],
            details=" ".join([manifest["attribution"], manifest["rights_evidence"],
                              "Decoded to lossless RGB PNG at original dimensions for DOCX compatibility; "
                              "unchanged supplier originals and checksums retained.",
                              manifest["note"], "PDF label: " + mapping["label"],
                              mapping.get("note", "")]),
        )
        if len(matches) == 1:
            references[record["source_id"]] = dict(record, content=rendered.getvalue())
        audit.append(record)
    return references, audit


def load_manifest(root, rows, path):
    if not path.exists():
        return {}, []
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported review-reference schema")
    source = safe_asset(root, manifest["source"]).read_bytes()
    if hashlib.sha256(source).hexdigest() != manifest["source_sha256"]:
        raise ValueError("AI contact-sheet checksum changed; fresh crop review required")
    by_identity = defaultdict(list)
    for row in rows:
        by_identity[(row["plu"], row["name"])].append(row)
    references, audit, seen = {}, [], set()
    with Image.open(io.BytesIO(source)) as image:
        image.load()
        if list(image.size) != manifest["source_size"]:
            raise ValueError("AI contact-sheet dimensions changed")
        for panel in manifest["panels"]:
            identity = (panel["plu"], panel["product"])
            if not all(isinstance(value, str) and value for value in identity) or identity in seen:
                raise ValueError("review references require unique exact string identities")
            seen.add(identity)
            box = panel["box"]
            if (not isinstance(box, list) or len(box) != 4 or
                    any(type(value) is not int for value in box) or
                    not (0 <= box[0] < box[2] <= image.width and
                         0 <= box[1] < box[3] <= image.height)):
                raise ValueError(f"{identity}: invalid reviewed crop box")
            if panel["decision"] not in {"REVIEW_REFERENCE", "REJECTED"}:
                raise ValueError(f"{identity}: invalid review-reference decision")
            matches = by_identity[identity]
            if panel.get("source_id"):
                matches = [row for row in matches if row["source_id"] == panel["source_id"]]
            record = dict(
                source_id=matches[0]["source_id"] if len(matches) == 1 else "",
                plu=panel["plu"], product=panel["product"], decision=panel["decision"],
                status=panel["decision"], source_document=manifest["source"],
                source_sha256=manifest["source_sha256"], crop_box=json.dumps(box),
                crop_sha256="", width=box[2] - box[0], height=box[3] - box[1],
                details=" ".join(filter(None, [
                    manifest["origin"], manifest["review_note"], panel.get("note", ""),
                ])),
            )
            if not matches:
                record["status"] = "NO_ACTIVE_EXACT_IDENTITY"
            elif len(matches) != 1:
                record["status"] = "AMBIGUOUS_DUPLICATE_IDENTITY"
                record["details"] += " Not copied to multiple XML records; individual review required."
            elif panel["decision"] == "REVIEW_REFERENCE":
                content = io.BytesIO()
                image.crop(box).convert("RGB").save(content, format="PNG")
                record["crop_sha256"] = hashlib.sha256(content.getvalue()).hexdigest()
                references[record["source_id"]] = dict(record, content=content.getvalue())
            audit.append(record)
    return references, audit
