"""Read the owner-maintained PickList without modifying or correcting its values."""
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def flag(item, name, default=None):
    value = item.findtext(name)
    if value is None and default is not None:
        return default
    if value not in {"True", "False"}:
        raise ValueError(f"PLU {item.get('UPC')!r}: {name} must be True or False")
    return value == "True"


def read_picklist(path):
    content = Path(path).read_bytes()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"cannot parse owner-supplied PickList.xml: {exc}") from exc
    if root.tag != "PickList" or root.find("Items") is None:
        raise ValueError("expected PickList/Items in source XML")
    rows, occurrences = [], Counter()
    items = root.findall("./Items/Item")
    for position, item in enumerate(items, 1):
        plu = item.get("UPC")
        name = item.findtext("./Languages/Language[@LCID='0409']/Description")
        department = item.findtext("Department", "")
        visible = flag(item, "IsVisible")
        deleted = flag(item, "DeleteThisItem", default=False)
        if not isinstance(plu, str) or not plu.strip():
            raise ValueError(f"XML item {position}: missing UPC")
        if name is None:
            raise ValueError(f"XML item {position}: missing English (0409) description")
        identity = (plu, name, department)
        occurrences[identity] += 1
        key = json.dumps([*identity, occurrences[identity]], ensure_ascii=False,
                         separators=(",", ":"))
        rows.append(dict(
            source_id=hashlib.sha256(key.encode("utf-8")).hexdigest(),
            source_position=position, occurrence=occurrences[identity],
            plu=plu, name=name, department=department, visible=visible, deleted=deleted,
            included=visible and not deleted,
            picture_references=[picture.text or "" for picture in item.findall("./Pictures/Picture")],
        ))
    if not rows:
        raise ValueError("PickList contains no items")
    return rows, hashlib.sha256(content).hexdigest()


def read_assignments(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("assignments"), list):
        raise ValueError("expected schema_version 1 and an assignments list")
    result = {}
    for row in data["assignments"]:
        key = row["source_id"]
        if key in result:
            raise ValueError(f"duplicate assignment source_id: {key}")
        if row.get("book") not in {"Fruit", "Vegetable", "Non-produce"}:
            raise ValueError(f"assignment {key}: unsupported or missing book")
        result[key] = row
    return result
