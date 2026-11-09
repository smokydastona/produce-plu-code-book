"""Apply and verify the standard pink ORGANIC identification watermark.

Original images remain unchanged inside the supplied visual DOCX files.
The label identifies the PickList entry; it does not certify the photograph.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import deque
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
VERSION = "PINK_ORGANIC_LEAF_SEAL_TOP_LEFT_V3"
MANIFEST = "organic_watermarks.json"
BADGE_SOURCE = "data/branding/Organic_Pink_Leaf_Seal.png"
BOOKS = {"Fruit": "FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.docx",
         "Vegetable": "VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.docx"}
BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def is_organic(row):
    return any(re.search(r"\borganic\b", row.get(key, ""), re.I)
               for key in ("name", "category", "section"))


@lru_cache(maxsize=1)
def badge_artwork():
    source = ROOT / BADGE_SOURCE
    if not source.exists():
        raise ValueError(f"missing organic badge source artwork: {source}")
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    pixels = image.load()
    width, height = image.size
    queue = deque()
    seen = set()

    def near_white(x, y):
        r, g, b, a = pixels[x, y]
        return a > 0 and r >= 245 and g >= 245 and b >= 245

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen or not near_white(x, y):
            continue
        seen.add((x, y))
        pixels[x, y] = (255, 255, 255, 0)
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    alpha = image.getchannel("A")
    box = alpha.getbbox()
    image = image.crop(box) if box else image
    result = io.BytesIO()
    image.save(result, format="PNG")
    return result.getvalue()


def render_watermark(content, *, minimum_side=40):
    with Image.open(io.BytesIO(content)) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    size = min(image.size)
    margin = max(2, round(size * 0.025))
    side = min(size - margin * 2, max(minimum_side, round(size * 0.30)))
    if side < 1:
        raise ValueError("image is too small for the organic badge")
    with Image.open(io.BytesIO(badge_artwork())) as badge:
        badge = badge.resize((side, side), Image.Resampling.LANCZOS)
    image.alpha_composite(badge, (margin, margin))
    result = io.BytesIO()
    image.convert("RGB").save(result, format="PNG")
    return result.getvalue()


def read_records(image_root):
    path = image_root / MANIFEST
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected a list of watermark records")
    by_idx = {}
    for record in records:
        if record["idx"] in by_idx:
            raise ValueError(f"{path}: repeated entry {record['idx']}")
        by_idx[record["idx"]] = record
    return by_idx


def original_content(record, root):
    source = record["source_document"]
    member = record["source_member"]
    if source not in {f"sources/visual/{name.replace('_PRODUCTION', '_CORRECTED')}"
                      for name in BOOKS.values()} or not member.startswith("word/media/"):
        raise ValueError("watermark original must be media in a supplied visual DOCX")
    with zipfile.ZipFile(root / source) as archive:
        content = archive.read(member)
    if hashlib.sha256(content).hexdigest() != record["original_sha256"]:
        raise ValueError(f"entry {record['idx']}: original image checksum mismatch")
    return content


def verified_original(row, record, image_root, allow_legacy=False):
    from check_image_uniqueness import image_fingerprint

    if record is None:
        raise ValueError(f"organic entry {row['idx']}: missing pink ORGANIC watermark record")
    for key in ("idx", "book", "plu", "image"):
        if record[key] != row[key]:
            raise ValueError(f"entry {row['idx']}: watermark record {key} mismatch")
    legacy = allow_legacy and record["watermark"] == "PINK_ORGANIC_BADGE_TOP_LEFT_V2"
    if record["watermark"] != VERSION and not legacy:
        raise ValueError(f"entry {row['idx']}: unsupported organic watermark")
    if not legacy and record.get("badge_sha256") != hashlib.sha256(badge_artwork()).hexdigest():
        raise ValueError(f"entry {row['idx']}: organic badge checksum mismatch")
    content = original_content(record, image_root.parent)
    expected = render_watermark(content)
    if image_fingerprint(image_root / row["image"]) != image_fingerprint(io.BytesIO(expected)):
        raise ValueError(f"organic entry {row['idx']}: missing or altered pink ORGANIC watermark")
    return content


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def write_csv(path, rows, encoding="utf-8-sig"):
    with path.open("w", newline="", encoding=encoding) as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def verify_booklets(root, rows):
    import docx
    from docx.oxml.ns import qn
    from check_image_uniqueness import image_fingerprint

    index = 0
    for book, filename in BOOKS.items():
        document = docx.Document(root / "current/booklets" / filename)
        for cell in document.element.body.iter(qn("w:tc")):
            texts = ["".join(node.text or "" for node in p.iter(qn("w:t")))
                     for p in cell.iter(qn("w:p"))]
            plu = next((text[5:].strip() for text in texts if text.startswith("PLU:")), None)
            if plu is None:
                continue
            row = rows[index]
            index += 1
            name = texts[texts.index("PLU: " + plu) + 1]
            if (row["book"], row["plu"], row["name"]) != (book, plu, name):
                raise ValueError(f"booklet and entry table differ at entry {row['idx']}")
            blips = list(cell.iter(BLIP))
            if len(blips) != 1:
                raise ValueError(f"entry {row['idx']}: expected exactly one embedded image")
            content = document.part.related_parts[blips[0].get(EMBED)].blob
            if image_fingerprint(io.BytesIO(content)) != image_fingerprint(root / "data" / row["image"]):
                raise ValueError(f"entry {row['idx']}: booklet and standalone image differ")
    if index != len(rows):
        raise ValueError("entry table contains entries absent from the booklets")


def update_workbook(root, rows, records):
    import openpyxl
    from check_image_uniqueness import audit_entries

    path = root / "current/reports/BOOKLET_AUDIT_REPORT.xlsx"
    workbook = openpyxl.load_workbook(path)
    for name in ("Organic Watermarks", "Image Uniqueness"):
        if name in workbook.sheetnames:
            del workbook[name]
    sheet = workbook.create_sheet("Organic Watermarks")
    sheet.append(["Entry #", "Book", "PLU", "Image", "Watermark", "Unchanged Source", "Source Member"])
    for record in records:
        sheet.append([record[key] for key in
                      ("idx", "book", "plu", "image", "watermark", "source_document", "source_member")])
    sheet.freeze_panes = "A2"
    groups = audit_entries(rows, root / "data")
    sheet = workbook.create_sheet("Image Uniqueness")
    sheet.append(["Rule", "Unique per entry; matching conventional/organic photo reuse allowed with pink ORGANIC watermark"])
    sheet.append(["Organic entries with verified watermark", len(records)])
    sheet.append(["Prohibited duplicate groups", len(groups)])
    sheet.append(["Entries in prohibited groups", sum(map(len, groups))])
    sheet.append(["Status", "NOT COMPLIANT" if groups else "PASS"])
    sheet.append(["Watermark meaning", "PickList organic entry label; not photo or organic certification"])
    workbook.save(path)


def apply(root):
    import docx
    from docx.oxml.ns import qn

    data = root / "data"
    rows = read_csv(data / "entries.csv")
    previous = read_records(data)
    originals = {}
    for book in BOOKS.values():
        source = "sources/visual/" + book.replace("_PRODUCTION", "_CORRECTED")
        with zipfile.ZipFile(root / source) as archive:
            for member in archive.namelist():
                if member.startswith("word/media/"):
                    content = archive.read(member)
                    originals[hashlib.sha256(content).hexdigest()] = (source, member, content)
    records, rendered, old_paths = [], {}, []
    for row in rows:
        if not is_organic(row):
            continue
        old_path = data / row["image"]
        if row["idx"] in previous:
            old_record = previous[row["idx"]]
            content = verified_original(row, old_record, data, allow_legacy=True)
            source, member = old_record["source_document"], old_record["source_member"]
        else:
            digest = hashlib.sha256(old_path.read_bytes()).hexdigest()
            if digest not in originals:
                raise ValueError(f"entry {row['idx']}: original not found in supplied source documents")
            source, member, content = originals[digest]
        row["image"] = str(Path(row["image"]).with_suffix(".png"))
        record = {key: row[key] for key in ("idx", "book", "plu", "image")}
        record.update(watermark=VERSION, source_document=source, source_member=member,
                      original_sha256=hashlib.sha256(content).hexdigest(),
                      badge_sha256=hashlib.sha256(badge_artwork()).hexdigest())
        records.append(record)
        rendered[row["idx"]] = render_watermark(content)
        old_paths.append(old_path)

    documents = {}
    index = 0
    for book, filename in BOOKS.items():
        document = docx.Document(root / "current/booklets" / filename)
        for cell in document.element.body.iter(qn("w:tc")):
            texts = ["".join(node.text or "" for node in p.iter(qn("w:t")))
                     for p in cell.iter(qn("w:p"))]
            plu = next((text[5:].strip() for text in texts if text.startswith("PLU:")), None)
            if plu is None:
                continue
            row = rows[index]
            index += 1
            name = texts[texts.index("PLU: " + plu) + 1]
            if (row["book"], row["plu"], row["name"]) != (book, plu, name):
                raise ValueError(f"booklet and entry table differ at entry {row['idx']}")
            if row["idx"] in rendered:
                blips = list(cell.iter(BLIP))
                if len(blips) != 1:
                    raise ValueError(f"entry {row['idx']}: expected exactly one embedded image")
                relationship, _ = document.part.get_or_add_image(io.BytesIO(rendered[row["idx"]]))
                blips[0].set(EMBED, relationship)
        used_images = {node.get(EMBED) for node in document.element.iter(BLIP)}
        image_relationships = [
            key for key, relationship in document.part.rels.items()
            if relationship.reltype.endswith("/image") and key not in used_images
        ]
        for key in image_relationships:
            if document.part._rel_ref_count(key) == 0:
                document.part.drop_rel(key)
        documents[filename] = document
    if index != len(rows):
        raise ValueError("entry table contains entries absent from the booklets")

    for row in rows:
        if row["idx"] in rendered:
            (data / row["image"]).write_bytes(rendered[row["idx"]])
    for filename, document in documents.items():
        document.save(root / "current/booklets" / filename)
    (data / "branding").mkdir(exist_ok=True)
    (data / "branding/pink-organic-badge.png").write_bytes(badge_artwork())
    write_csv(data / "entries.csv", rows, encoding="utf-8")
    (data / MANIFEST).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    by_idx = {row["idx"]: row for row in rows}
    review = read_csv(data / "image_review.csv")
    for row in review:
        row["image"] = by_idx[row["idx"]]["image"]
    write_csv(data / "image_review.csv", review)
    for filename, field in (("MASTER_IMAGE_LIBRARY.csv", "Image File"),
                            ("IMAGE_MATCH_REPORT.csv", "Assigned Image")):
        path = root / "current/reports" / filename
        report = read_csv(path)
        if len(report) != len(rows):
            raise ValueError(f"{filename}: entry count differs")
        for record, row in zip(report, rows):
            if (record["PLU"], record["Product"]) != (row["plu"], row["name"]):
                raise ValueError(f"{filename}: entry order differs")
            record[field] = "data/" + row["image"]
        write_csv(path, report)
    referenced = {data / row["image"] for row in rows}
    for path in old_paths:
        if path not in referenced:
            path.unlink()
    verify_booklets(root, rows)
    update_workbook(root, rows, records)
    print(f"Applied {VERSION} to {len(records)} organic entries; source images and review verdicts unchanged")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without modifying files")
    args = parser.parse_args()
    try:
        if args.check:
            rows = read_csv(ROOT / "data/entries.csv")
            records = read_records(ROOT / "data")
            if (ROOT / "data/branding/pink-organic-badge.png").read_bytes() != badge_artwork():
                raise ValueError("organic badge artwork differs from the standard design")
            for row in rows:
                if is_organic(row):
                    verified_original(row, records.get(row["idx"]), ROOT / "data")
            verify_booklets(ROOT, rows)
            print(f"Verified {sum(is_organic(row) for row in rows)} standard pink ORGANIC watermarks")
        else:
            apply(ROOT)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
