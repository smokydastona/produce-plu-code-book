"""Identity-linked AI crops for review copies only; never grant image approvals."""
import hashlib
import io
import json
from collections import defaultdict

from PIL import Image

from sync_picklist import safe_asset

MANIFESTS = (
    "data/review-references/additional-36-ai.json",
    "data/review-references/missing-ai.json",
)


def load_references(root, rows):
    references, audit = {}, []
    for name in MANIFESTS:
        selected, records = load_manifest(root, rows, root / name)
        if references.keys() & selected.keys():
            raise ValueError("multiple AI references for the same source identity")
        references.update(selected)
        audit.extend(records)
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
