"""Generate full till-binder review copies with updated Produce and Deli sheets."""
import argparse
import copy
import csv
import hashlib
import io
import json
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from docx import Document
from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image as DocxImage
from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image as DocxImage
from docx.oxml.ns import qn
from lxml import etree as ET
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.cell import range_boundaries, get_column_letter
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.page import PageMargins
from PIL import Image, ImageOps

from check_image_uniqueness import image_fingerprint
from organic_watermarks import render_watermark
from picklist_catalog import read_assignments, read_picklist
from review_image_references import load_references
from sync_picklist import (booklet_order, csv_output, organic, organic_display_section,
                           reconcile)
from working_list import read_working_list
from build_deli_sheet import DELI_SOURCE, read_source as read_deli_source, validate_sheet as validate_deli_sheet

ROOT = Path(__file__).resolve().parents[1]
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"s": S, "r": R, "p": P}
FILENAMES = {
    "photos": "Complete Till Binder - Updated - Photos.xlsx",
}
MAX_WORKBOOK_IMAGE_SIZE = (192, 120)
MAX_GITHUB_FILE_SIZE = 100 * 1024 * 1024
VISUALS = {
    "Fruit": "FRUIT_VISUAL_PLU_BOOKLET_CORRECTED.docx",
    "Vegetable": "VEGETABLE_VISUAL_PLU_BOOKLET_CORRECTED.docx",
}
MAX_WORKBOOK_IMAGE_SIZE = (192, 120)
MAX_GITHUB_FILE_SIZE = 100 * 1024 * 1024
BLOCKS = (1, 6, 11)
LINES = 20
PAGE_ROWS = LINES + 3
BULK_SHEETS = ("Bulk", "Bulk (2)", "Bulk (3)", "Bulk (4)")


def sha(content):
    return hashlib.sha256(content).hexdigest()


def docx_compatible_image(content):
    try:
        DocxImage.from_blob(content)
    except UnrecognizedImageError:
        with Image.open(io.BytesIO(content)) as image:
            output = io.BytesIO()
            image.save(output, format="PNG")
        return output.getvalue()
    return content


def workbook_photo_copy(content):
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail(MAX_WORKBOOK_IMAGE_SIZE, Image.Resampling.LANCZOS)
        if "A" in image.getbands() or "transparency" in image.info:
            has_transparency = image.convert("RGBA").getchannel("A").getextrema()[0] < 255
        else:
            has_transparency = False
        profile = {}
        if image.info.get("icc_profile"):
            profile["icc_profile"] = image.info["icc_profile"]
        output = io.BytesIO()
        if has_transparency:
            image.save(output, format="PNG", optimize=True, **profile)
        else:
            image.convert("RGB").save(
                output, format="JPEG", quality=90, optimize=True, progressive=True, **profile)
        return output.getvalue()


def xml(content):
    return ET.fromstring(content, ET.XMLParser(resolve_entities=False, no_network=True))


def serialize(element):
    return ET.tostring(element, encoding="UTF-8", xml_declaration=True, standalone=True)


def resolve_part(part, target):
    result = posixpath.normpath(target.lstrip("/") if target.startswith("/") else
                               posixpath.join(posixpath.dirname(part), target))
    if result.startswith("../"):
        raise ValueError(f"out-of-package relationship: {target}")
    return result


def rels_part(part):
    folder, filename = posixpath.split(part)
    return posixpath.join(folder, "_rels", filename + ".rels")


def sheet_info(archive, name="Produce"):
    workbook = xml(archive.read("xl/workbook.xml"))
    relationships = {rel.get("Id"): rel.get("Target") for rel in
                     xml(archive.read("xl/_rels/workbook.xml.rels"))}
    for index, sheet in enumerate(workbook.find(f"{{{S}}}sheets")):
        if sheet.get("name") == name:
            return resolve_part("xl/workbook.xml", relationships[sheet.get(f"{{{R}}}id")]), index
    raise ValueError(f"original binder has no {name!r} sheet")


def combine_bulk(binder, destination):
    """Combine the four original print regions without resaving unrelated workbook parts."""
    with zipfile.ZipFile(binder) as original:
        workbook = xml(original.read("xl/workbook.xml"))
        sheets = workbook.find(f"{{{S}}}sheets")
        sheet_names = [node.get("name") for node in sheets]
        present = [name for name in BULK_SHEETS if name in sheet_names]
        if not any(name in present for name in BULK_SHEETS[1:]):
            shutil.copyfile(binder, destination)
            return False
        if present != list(BULK_SHEETS) or [sheet_names.index(n) for n in BULK_SHEETS] != list(
                range(sheet_names.index("Bulk"), sheet_names.index("Bulk") + 4)):
            raise ValueError("the four Bulk sheets must be present and consecutive")
        paths = [sheet_info(original, name)[0] for name in BULK_SHEETS]
        trees = [xml(original.read(path)) for path in paths]
        permitted = {"sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData",
                     "mergeCells", "pageMargins", "pageSetup"}
        for path, tree in zip(paths, trees):
            if any(ET.QName(node).localname not in permitted for node in tree):
                raise ValueError(f"{path}: unsupported Bulk sheet feature; review before merging")
            relations = rels_part(path)
            if relations in original.namelist():
                for rel in xml(original.read(relations)):
                    if not rel.get("Type", "").endswith("/printerSettings"):
                        raise ValueError(f"{path}: unsupported Bulk relationship; review before merging")
        for tree in trees[1:]:
            for tag in ("cols", "sheetFormatPr", "pageMargins"):
                if ET.tostring(trees[0].find(f"{{{S}}}{tag}"), method="c14n") != ET.tostring(
                        tree.find(f"{{{S}}}{tag}"), method="c14n"):
                    raise ValueError(f"Bulk sheets have incompatible {tag}")
        names = workbook.find(f"{{{S}}}definedNames")
        indexes = [sheet_names.index(name) for name in BULK_SHEETS]
        areas = []
        for index in indexes:
            found = [n for n in names if n.get("localSheetId") == str(index) and
                     n.get("name") == "_xlnm.Print_Area"] if names is not None else []
            if len(found) != 1 or not found[0].text or "!" not in found[0].text:
                raise ValueError("each Bulk sheet must have one rectangular print area")
            bounds = range_boundaries(found[0].text.split("!", 1)[1].replace("$", ""))
            if bounds[0] != 2 or bounds[1] != 4 or bounds[2] != 9:
                raise ValueError("unexpected Bulk print area; review before merging")
            areas.append(bounds)
        # Do not silently drop owner edits outside the four printed regions.
        headers = []
        for tree, (_, start, _, end) in zip(trees, areas):
            header = []
            for row in tree.find(f"{{{S}}}sheetData"):
                for cell in row:
                    col, r, _, _ = range_boundaries(cell.get("r"))
                    if cell.find(f"{{{S}}}f") is not None:
                        raise ValueError("Bulk formulas require manual review before merging")
                    if cell.find(f"{{{S}}}v") is not None or cell.find(f"{{{S}}}is") is not None:
                        if r == 1 and col == 2:
                            header.append(ET.tostring(cell, method="c14n"))
                        elif not (start <= r <= end and 2 <= col <= 9):
                            raise ValueError("Bulk contains data outside its print area")
            headers.append(header)
        if any(header != headers[0] for header in headers[1:]):
            raise ValueError("Bulk sheet headers differ; review before merging")
        for path in original.namelist():
            if path.startswith("xl/worksheets/") and path.endswith(".xml") and path not in paths:
                tree = xml(original.read(path))
                for formula in tree.iter(f"{{{S}}}f"):
                    if formula.text and any(name in formula.text for name in BULK_SHEETS[1:]):
                        raise ValueError(f"{path}: formula references a Bulk sheet being merged")
        target = trees[0]
        data = target.find(f"{{{S}}}sheetData")
        for row in list(data):
            if int(row.get("r")) > areas[0][3]:
                data.remove(row)
        merges = target.find(f"{{{S}}}mergeCells")
        last = areas[0][3]
        breaks = []
        for tree, (_, start, _, end) in zip(trees[1:], areas[1:]):
            breaks.append(last)
            offset = last + 1 - start
            for row in tree.find(f"{{{S}}}sheetData"):
                row_number = int(row.get("r"))
                if start <= row_number <= end:
                    node = copy.deepcopy(row)
                    node.set("r", str(row_number + offset))
                    for cell in node:
                        col, r, _, _ = range_boundaries(cell.get("r"))
                        cell.set("r", f"{get_column_letter(col)}{r + offset}")
                    data.append(node)
            incoming = tree.find(f"{{{S}}}mergeCells")
            if incoming is not None:
                for merge in incoming:
                    min_col, min_row, max_col, max_row = range_boundaries(merge.get("ref"))
                    if min_row == 1 and max_row == 2:
                        continue
                    if min_row < start or max_row > end:
                        raise ValueError("Bulk merged cells extend beyond the print area")
                    if merges is None:
                        raise ValueError("Bulk merge layout requires manual review")
                    node = copy.deepcopy(merge)
                    node.set("ref", f"{get_column_letter(min_col)}{min_row + offset}:"
                                    f"{get_column_letter(max_col)}{max_row + offset}")
                    merges.append(node)
            last += end - start + 1
        if merges is not None:
            merges.set("count", str(len(merges)))
        target.find(f"{{{S}}}dimension").set("ref", f"B1:I{last}")
        setup = target.find(f"{{{S}}}pageSetup")
        setup.attrib.clear()
        setup.set("paperSize", "1")
        setup.set("orientation", "landscape")
        setup.set("scale", "65")
        target.find(f"{{{S}}}sheetPr").find(f"{{{S}}}pageSetUpPr").set("fitToPage", "0")
        row_breaks = ET.Element(f"{{{S}}}rowBreaks", count=str(len(breaks)),
                                manualBreakCount=str(len(breaks)))
        for number in breaks:
            ET.SubElement(row_breaks, f"{{{S}}}brk", id=str(number), min="0", max="16383", man="1")
        setup.addnext(row_breaks)
        for node in list(names):
            local = node.get("localSheetId")
            if local is not None and int(local) in indexes:
                if node.get("name") != "_xlnm.Print_Area":
                    raise ValueError("Bulk local defined names require manual review")
                if int(local) == indexes[0]:
                    node.text = f"Bulk!$B$4:$I${last}"
                else:
                    names.remove(node)
            elif any(name in (node.text or "") for name in BULK_SHEETS[1:]):
                raise ValueError("defined name references a Bulk sheet being merged")
            elif local is not None:
                node.set("localSheetId", str(int(local) - sum(i < int(local) for i in indexes[1:])))
        for index in reversed(indexes[1:]):
            sheets.remove(sheets[index])
        for view in workbook.iter(f"{{{S}}}workbookView"):
            for attr in ("activeTab", "firstSheet"):
                if view.get(attr) is not None:
                    value = int(view.get(attr))
                    view.set(attr, str(indexes[0] if value in indexes[1:] else
                                       value - sum(i < value for i in indexes[1:])))
        changes = {paths[0]: serialize(target), "xl/workbook.xml": serialize(workbook)}
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as output:
            output.comment = original.comment
            for entry in original.infolist():
                output.writestr(entry, changes.get(entry.filename, original.read(entry.filename)))
        return True


def visual_records(root):
    records = defaultdict(list)
    for book, filename in VISUALS.items():
        path = root / "sources/visual" / filename
        document = Document(path)
        for cell in document.element.body.iter(qn("w:tc")):
            texts = ["".join(node.text or "" for node in paragraph.iter(qn("w:t")))
                     for paragraph in cell.iter(qn("w:p"))]
            positions = [i for i, text in enumerate(texts) if text.startswith("PLU: ")]
            if not positions:
                continue
            if len(positions) != 1 or positions[0] + 1 >= len(texts):
                raise ValueError(f"{filename}: cannot identify a visual-reference cell")
            position = positions[0]
            plu, name = texts[position][5:], texts[position + 1]
            blips = list(cell.iter(qn("a:blip")))
            if len(blips) != 1:
                raise ValueError(f"{filename}: {plu} / {name}: expected one embedded image")
            relation = blips[0].get(qn("r:embed"))
            part = document.part.related_parts[relation]
            source = next((text.split(": ", 1)[1] for text in texts
                           if text.startswith("Image Source: ")), "Unavailable")
            records[(plu, name)].append(dict(
                book=book, source_document=str(path.relative_to(root)),
                source_member=str(part.partname).lstrip("/"), image_source=source,
                original_sha256=sha(part.blob), content=part.blob,
            ))
    return records


def produce_catalog(items, assignments):
    rows, exclusions = [], []
    for item in items:
        if not item["included"]:
            exclusions.append(dict(item, reason="HIDDEN_OR_DELETED"))
            continue
        assignment = assignments.get(item["source_id"], {})
        classification_assignment = assignments.get(
            item.get("classification_source_id", item["source_id"])) or assignment
        if classification_assignment.get("book") == "Non-produce":
            exclusions.append(dict(item, reason="NON_PRODUCE_IN_OTHER_BINDER_SECTIONS"))
            continue
        book = classification_assignment.get("book")
        section = classification_assignment.get("section", "")
        status = "EXISTING_CLASSIFICATION" if book else "CLASSIFICATION_REVIEW_REQUIRED"
        if not book:
            status = "CLASSIFICATION_REVIEW_REQUIRED"
            if re.search(r"\bmelon\b", item["name"], re.I):
                book, section = "Fruit", "Melons"
            elif re.search(r"\bmushrooms?\b", item["name"], re.I):
                book, section = "Vegetable", "Specialty Vegetables"
            else:
                book, section = "Vegetable", "Unclassified PickList entries - REVIEW"
        row = dict(item, book=book, section=section, organic=organic(item),
                   classification_status=status)
        if not row["section"]:
            row["section"] = "Unclassified PickList entries - REVIEW"
        rows.append(row)
    ordered = sorted(booklet_order(rows, assignments),
                     key=lambda row: row["display_section"].casefold())
    counts = Counter(item["plu"] for item in items if item["included"])
    for row in ordered:
        row["duplicate_count"] = counts[row["plu"]]
    return ordered, exclusions


def map_images(root, rows, assignments, visuals, update_library=True):
    with (root / "data/image_review.csv").open(newline="", encoding="utf-8-sig") as file:
        reviews = {row["idx"]: row for row in csv.DictReader(file)}
    references, reference_audit = load_references(root, rows)
    rejected_references = {row["source_id"]: row for row in reference_audit
                           if row["status"] == "REJECTED"}
    from legacy_approval import legacy_approval, legacy_entries

    legacy_records = legacy_entries(root)
    images, report = {}, []
    for row in rows:
        assignment = assignments.get(row["source_id"], {})
        legacy_record = legacy_approval(root, row, assignment, legacy_records)
        record = dict(
            source_id=row["source_id"], source_identity_ids=";".join(row.get("source_ids", [])),
            plu=row["plu"], product=row["name"],
            image_status="MISSING", embedded=False, image_source="", source_document="",
            source_member="", original_sha256="", embedded_sha256="", width=0, height=0,
            visual_verdict="", visual_review_note="", rights_status="NOT_VERIFIED", photograph_status="NOT_VERIFIED",
            organic_badge=False, reused_by_entries=0, details="",
            image_approval_status=("APPROVED_LEGACY" if legacy_record else
                                   "APPROVED" if assignment.get("visual_approval_status") == "APPROVED"
                                   else "NOT_APPROVED"),
            approval_basis="OWNER_LEGACY_PREAPPROVED_POLICY" if legacy_record else "",
            legacy_entry_idx=legacy_record["idx"] if legacy_record else "",
            legacy_original_verdict=legacy_record["historical_review"]["verdict"]
            if legacy_record else "",
        )
        if legacy_record:
            from sync_picklist import reviewed_image

            content, width, height, errors = reviewed_image(
                root, row, assignment, legacy_approved=True)
            if errors:
                record.update(
                    image_status="LEGACY_ASSIGNMENT_INVALID",
                    details="Legacy approval does not bypass invalid image or identity checks: " +
                            "; ".join(errors),
                )
                report.append(record)
                continue
            rendered = render_watermark(content) if row["organic"] else docx_compatible_image(content)
            images[row["source_id"]] = rendered
            review = legacy_record["historical_review"]
            record.update(
                image_status="LEGACY_PREAPPROVED_IMAGE", embedded=True,
                image_source=legacy_record["source"], source_document=legacy_record["image"],
                source_member=legacy_record["idx"], original_sha256=sha(content),
                embedded_sha256=sha(rendered), width=width, height=height,
                visual_verdict="APPROVED_LEGACY",
                visual_review_note="Approved under owner policy; original verdict: " + review["verdict"],
                rights_status=assignment.get("rights_verification_status", "NOT_VERIFIED"),
                photograph_status=assignment.get("photographic_origin", "NOT_VERIFIED"),
                organic_badge=row["organic"],
                details=("Owner policy treats every exact legacy entry as pre-approved. "
                         "Original visual verdict, image source, rights and provenance records remain "
                         "in the external audit report."),
                fingerprint=image_fingerprint(io.BytesIO(content)),
            )
            report.append(record)
            continue
        if assignment.get("visual_approval_status") == "APPROVED":
            from sync_picklist import reviewed_image

            content, width, height, errors = reviewed_image(root, row, assignment)
            if errors:
                if row.get("identity_changed"):
                    record.update(
                        image_status="APPROVED_ASSIGNMENT_INVALID",
                        details="Explicit WorkingList image assignment failed validation: " +
                                "; ".join(errors),
                    )
                    report.append(record)
                    continue
            else:
                provenance = assignment.get("provenance", {})
                rendered = render_watermark(content) if row["organic"] else docx_compatible_image(content)
                images[row["source_id"]] = rendered
                record.update(
                    image_status="APPROVED_WORKINGLIST_IMAGE", embedded=True,
                    image_source=provenance.get("source_page_url", ""),
                    original_sha256=sha(content), embedded_sha256=sha(rendered),
                    width=width, height=height, visual_verdict="Approved",
                    visual_review_note="Approved for this exact WorkingList assignment",
                    rights_status=assignment.get("rights_verification_status", "NOT_VERIFIED"),
                    photograph_status=assignment.get("photographic_origin", "NOT_VERIFIED"),
                    organic_badge=row["organic"],
                    details=("Decoded to lossless PNG for DOCX compatibility; unchanged approved original retained. "
                             if not row["organic"] and rendered != content else "") +
                            "Explicitly approved for this exact WorkingList identity; " +
                            ("owner-confirmed permission, not a public licence."
                             if assignment.get("rights_verification_status") ==
                             "OWNER_CONFIRMED_PERMISSION" else
                             "rights status recorded in the external assignment audit."),
                    fingerprint=image_fingerprint(io.BytesIO(content)),
                )
                report.append(record)
                continue
        reference = references.get(row["source_id"])
        if reference:
            supplier = reference["status"] == "SUPPLIER_REFERENCE"
            content = reference["content"]
            rendered = render_watermark(content, minimum_side=1) if row["organic"] else content
            images[row["source_id"]] = rendered
            record.update(
                image_status="SUPPLIER_REFERENCE_REVIEW" if supplier else "SUPPLIED_AI_CROP_REVIEW",
                embedded=True,
                image_source=reference["image_source"] if supplier else "AI Generated",
                source_document=reference["source_document"],
                source_member=reference["source_member"] if supplier else "crop " + reference["crop_box"],
                original_sha256=reference["crop_sha256"], embedded_sha256=sha(rendered),
                width=reference["width"], height=reference["height"],
                visual_verdict="REVIEW_REFERENCE_NOT_APPROVED",
                visual_review_note=reference["details"], organic_badge=row["organic"],
                photograph_status="SUPPLIER_PUBLISHED_PHOTO" if supplier else "AI_ILLUSTRATION_NOT_PHOTOGRAPH",
                rights_status=reference["rights_status"] if supplier else "NOT_VERIFIED",
                details=reference["details"] if supplier else
                        "Owner-supplied AI illustration cropped without labels; below 500 px. "
                        "Variety, rights and production approval remain unverified.",
                fingerprint=image_fingerprint(io.BytesIO(content)),
            )
            report.append(record)
            continue
        candidates = visuals.get((row["plu"], row["name"]), [])
        review = reviews.get(assignment.get("legacy_entry_idx"), {})
        if not candidates or not assignment or (
                assignment.get("reviewed_plu"), assignment.get("reviewed_product")) != (
                    row["plu"], row["name"]):
            record["details"] = (
                "WorkingList product identity changed; fresh product-specific image review is required. "
                "No prior image association was reused." if row.get("identity_changed") else
                "No reviewed identity-linked association to a supplied visual reference")
        elif len({candidate["original_sha256"] for candidate in candidates}) != 1:
            record["image_status"] = "AMBIGUOUS_REFERENCE"
            record["details"] = "Exact code/description has multiple different source images; left blank"
        elif (review.get("plu"), review.get("name")) != (row["plu"], row["name"]):
            record["image_status"] = "REVIEW_IDENTITY_MISMATCH"
            record["details"] = "Legacy review does not identify this exact product; left blank"
        else:
            candidate = candidates[0]
            content = candidate["content"]
            record.update({key: value for key, value in candidate.items() if key not in {"content", "book"}})
            record["visual_verdict"] = review["verdict"]
            record["visual_review_note"] = review.get("note", "")
            if candidate["image_source"] == "AI Generated":
                record["photograph_status"] = "AI_ILLUSTRATION_NOT_PHOTOGRAPH"
            with Image.open(io.BytesIO(content)) as image:
                record["width"], record["height"] = ImageOps.exif_transpose(image).size
            if sha(content) != assignment.get("image_sha256"):
                record["image_status"] = "SOURCE_CHECKSUM_CHANGED"
                record["details"] = "Supplied original differs from the assignment evidence; left blank"
            elif review["verdict"] == "Rejected":
                record["image_status"] = "VISUAL_REVIEW_REQUIRED"
                record["details"] = "Rejected variety match; left blank, not substituted"
            elif candidate["image_source"] != "AI Generated" and review["verdict"] != "Approved":
                record["image_status"] = "VISUAL_REVIEW_REQUIRED"
                record["details"] = "Approximate variety match; left blank, not substituted"
            else:
                artificial = candidate["image_source"] == "AI Generated"
                record["image_status"] = "AI_ILLUSTRATION_REFERENCE_REVIEW" if artificial else "SUPPLIED_REFERENCE_REVIEW"
                record["details"] = ("Existing AI-generated illustration retained as a visual reference, "
                                     "not a photograph. " if artificial else
                                     "Supplied visual reference; photographic origin unverified. ")
                if review["verdict"] != "Approved":
                    record["details"] += "Existing visual verdict is uncertain; owner must verify the image. "
                record["details"] += "Rights unverified; owner review required."
                if min(record["width"], record["height"]) < 500:
                    record["details"] += " Original below 500 px; not production-approved."
                rendered = render_watermark(content) if row["organic"] else content
                images[row["source_id"]] = rendered
                record.update(embedded=True, embedded_sha256=sha(rendered),
                              organic_badge=row["organic"])
                record["fingerprint"] = image_fingerprint(io.BytesIO(content))
        if row["source_id"] in rejected_references:
            record["details"] += " New AI panel excluded: " + rejected_references[row["source_id"]]["details"]
        report.append(record)
    counts = Counter(record["fingerprint"] for record in report if record.get("fingerprint"))
    for record in report:
        record["reused_by_entries"] = counts.get(record.get("fingerprint"), 0)
        if record["reused_by_entries"] > 1:
            record["details"] += " Shared source photograph/illustration; reuse requires review."
    if update_library:
        from used_image_library import record_images

        record_images(root, "WORKING_LIST_IMAGES.json", images, [
            dict(record, assignment=assignments.get(record["source_id"], {}),
                 library_approval_status=record["image_approval_status"])
            for record in report
        ])
    return images, report


def old_entries(binder):
    workbook = load_workbook(binder, read_only=False, data_only=False)
    try:
        sheet = workbook["Produce"]
        rows = []
        for column in (1, 4, 8):
            heading = ""
            for number in range(1, sheet.max_row + 1):
                cell, description = sheet.cell(number, column), sheet.cell(number, column + 1)
                if cell.value is None:
                    if description.value:
                        rows.append(dict(cell=cell.coordinate, original_code="", original_description=str(
                            description.value), heading=heading, issue="DESCRIPTION_WITHOUT_CODE"))
                    continue
                value = str(cell.value)
                code = value.strip()
                if re.fullmatch(r"[0-9]+", code):
                    rows.append(dict(cell=cell.coordinate, original_code=value,
                                     original_description=str(description.value or ""),
                                     heading=heading, issue="CODE_WHITESPACE" if value != code else ""))
                else:
                    heading = value
        return rows
    finally:
        workbook.close()


def comparisons(old, items, rows):
    active = defaultdict(list)
    all_codes = defaultdict(list)
    names = defaultdict(list)
    for item in items:
        all_codes[item["plu"]].append(item)
        if item["included"]:
            active[item["plu"]].append(item)
            names[item["name"]].append(item)
    changes = []
    for entry in old:
        code = entry["original_code"].strip()
        description = entry["original_description"]
        candidates = active.get(code, [])
        exact = [item for item in candidates if item["name"] == description]
        if not code:
            status = "ORIGINAL_DESCRIPTION_WITHOUT_CODE"
        elif exact:
            status = "EXACT_ACTIVE_RECORD"
        elif candidates:
            status = "CODE_ACTIVE_DESCRIPTION_DIFFERS_REVIEW"
        elif all_codes.get(code):
            status = "CODE_ONLY_HIDDEN_OR_DELETED"
        elif names.get(description):
            status = "POSSIBLE_CODE_CHANGE_EXACT_NAME_REVIEW"
            candidates = names[description]
        else:
            status = "NOT_IN_CURRENT_SOURCE_UNRESOLVED"
        changes.append(dict(entry, status=status, active_match_count=len(candidates),
                            candidate_source_ids=";".join(item["source_id"] for item in candidates),
                            current_codes=json.dumps([item["plu"] for item in candidates]),
                            current_descriptions=json.dumps([item["name"] for item in candidates],
                                                            ensure_ascii=False)))
    pairs = Counter((entry["original_code"].strip(), entry["original_description"]) for entry in old)
    codes = {entry["original_code"].strip() for entry in old}
    additions = [dict(source_id=row["source_id"], plu=row["plu"], product=row["name"],
                      status="EXACT_PAIR_IN_ORIGINAL" if pairs[(row["plu"], row["name"])] else
                      "DESCRIPTION_UPDATED_REVIEW" if row["plu"] in codes else "CODE_NOT_IN_ORIGINAL")
                 for row in rows]
    return changes, additions


def layout_rows(rows):
    """Fill three familiar top-to-bottom blocks, repeating category labels at breaks."""
    layout, index, block = [], 0, 0
    while index < len(rows):
        line, previous = 0, None
        while line < LINES and index < len(rows):
            row = rows[index]
            category = row["display_section"]
            if category != previous:
                if line == LINES - 1:
                    break
                layout.append(dict(kind="heading", block=block, line=line, text=category))
                line += 1
                previous = category
            if line == LINES:
                break
            layout.append(dict(kind="product", block=block, line=line, record=row))
            line += 1
            index += 1
        block += 1
    return layout


def set_text(cell, value):
    if len(value) > 32767:
        raise ValueError("source text exceeds Excel's cell length; refusing truncation")
    cell.value = value
    cell.data_type = "s"
    cell.number_format = "@"


def quick_sheet(rows, images, with_photos, title="PRODUCE"):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Produce"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "B4"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_LETTER
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.page_setup.pageOrder = "downThenOver"
    sheet.page_margins = PageMargins(left=.3, right=.3, top=.3, bottom=.3, header=.1, footer=.1)
    sheet.oddFooter.center.text = title.title() + " | Page &P of &N"
    sheet.oddFooter.center.size = 8
    sheet.oddFooter.center.font = "DejaVu Sans"
    for base in BLOCKS:
        for offset, width in enumerate((8, 13, 13, 8)):
            sheet.column_dimensions[sheet.cell(1, base + offset).column_letter].width = width
    for column in ("E", "J"):
        sheet.column_dimensions[column].width = 1.5
    layout = layout_rows(rows)
    pages = max(1, max((entry["block"] // 3 + 1 for entry in layout), default=1))
    for page in range(pages):
        start = page * PAGE_ROWS + 1
        for offset, height in enumerate((18, 18, 18)):
            sheet.row_dimensions[start + offset].height = height
        for number in range(start + 3, start + PAGE_ROWS):
            sheet.row_dimensions[number].height = 25
        sheet.merge_cells(start_row=start, start_column=1, end_row=start, end_column=14)
        set_text(sheet.cell(start, 1), title + " PLU QUICK GUIDE - " +
                 ("VISUAL REFERENCES" if with_photos else "TEXT ONLY"))
        sheet.cell(start, 1).font = Font(name="DejaVu Sans", size=13, bold=True)
        sheet.merge_cells(start_row=start + 1, start_column=1, end_row=start + 1, end_column=14)
        set_text(sheet.cell(start + 1, 1), "Red PLU = shared code: confirm the product before entry")
        sheet.cell(start + 1, 1).font = Font(name="DejaVu Sans", size=8, bold=True, color="9C0006")
        for base in BLOCKS:
            sheet.merge_cells(start_row=start + 2, start_column=base + 1,
                              end_row=start + 2, end_column=base + 2)
            for column, value in ((base, "PLU"), (base + 1, "PRODUCT"), (base + 3, "")):
                cell = sheet.cell(start + 2, column)
                set_text(cell, value)
                cell.font = Font(name="DejaVu Sans", size=9, bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="305040")
        if page:
            sheet.row_breaks.append(Break(id=start - 1))
    coordinates = []
    for entry in layout:
        base = BLOCKS[entry["block"] % 3]
        number = (entry["block"] // 3) * PAGE_ROWS + 4 + entry["line"]
        if entry["kind"] == "heading":
            sheet.merge_cells(start_row=number, start_column=base, end_row=number, end_column=base + 3)
            cell = sheet.cell(number, base)
            set_text(cell, entry["text"])
            cell.font = Font(name="DejaVu Sans", size=9, bold=True)
            cell.fill = PatternFill("solid", fgColor="DCE6DA")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            continue
        row = entry["record"]
        code, description, photo = [sheet.cell(number, base + offset) for offset in (0, 1, 3)]
        sheet.merge_cells(start_row=number, start_column=base + 1, end_row=number, end_column=base + 2)
        set_text(code, row["plu"])
        set_text(description, row["name"])
        for cell in (code, description, photo):
            cell.font = Font(name="DejaVu Sans", size=9.5, bold=cell is code)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.border = Border(bottom=Side(style="hair", color="D0D0D0"))
        if row["duplicate_count"] > 1:
            code.fill = PatternFill("solid", fgColor="FFC7CE")
            code.font = Font(name="DejaVu Sans", size=9.5, bold=True, color="9C0006")
        if with_photos:
            content = images.get(row["source_id"])
            if content:
                picture = ExcelImage(io.BytesIO(content))
                factor = min(48 / picture.width, 30 / picture.height)
                picture.width *= factor
                picture.height *= factor
                sheet.add_image(picture, photo.coordinate)
        coordinates.append(dict(
            source_id=row["source_id"], plu=row["plu"], product=row["name"],
            code_cell=code.coordinate, description_cell=description.coordinate,
            image_cell=photo.coordinate, page=entry["block"] // 3 + 1,
            duplicate_count=row["duplicate_count"],
        ))
    sheet.print_area = f"A1:N{pages * PAGE_ROWS}"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), coordinates, pages


def merge_styles(original_content, donor_content):
    original, donor = xml(original_content), xml(donor_content)
    mappings = {}
    for name in ("numFmts", "fonts", "fills", "borders", "cellStyleXfs", "cellXfs"):
        incoming = donor.find(f"{{{S}}}{name}")
        if incoming is None:
            continue
        target = original.find(f"{{{S}}}{name}")
        if target is None:
            target = ET.Element(f"{{{S}}}{name}")
            # numFmts precedes fonts; all other standard collections exist in Excel binders.
            if name != "numFmts":
                raise ValueError(f"original styles lack {name}; cannot safely append styles")
            original.insert(0, target)
        mapping = {}
        next_format = max([163] + [int(node.get("numFmtId")) for node in target]) + 1 if name == "numFmts" else 0
        for index, element in enumerate(incoming):
            node = copy.deepcopy(element)
            if name == "numFmts":
                mapping[int(node.get("numFmtId"))] = next_format
                node.set("numFmtId", str(next_format))
                next_format += 1
            else:
                mapping[index] = len(target)
                if name in {"cellStyleXfs", "cellXfs"}:
                    for attr, collection in (("fontId", "fonts"), ("fillId", "fills"),
                                             ("borderId", "borders"), ("xfId", "cellStyleXfs")):
                        if node.get(attr) is not None and collection in mappings:
                            node.set(attr, str(mappings[collection][int(node.get(attr))]))
                    fmt = int(node.get("numFmtId", "0"))
                    if fmt in mappings.get("numFmts", {}):
                        node.set("numFmtId", str(mappings["numFmts"][fmt]))
            target.append(node)
        target.set("count", str(len(target)))
        mappings[name] = mapping
    return serialize(original), mappings["cellXfs"]


def replace_produce(binder, donor_content, destination):
    replace_sheet(binder, donor_content, destination, "Produce")


def replace_sheet(binder, donor_content, destination, sheet_name):
    with zipfile.ZipFile(binder) as original, zipfile.ZipFile(io.BytesIO(donor_content)) as donor:
        target, index = sheet_info(original, sheet_name)
        donor_sheet, _ = sheet_info(donor, sheet_name)
        styles, style_ids = merge_styles(original.read("xl/styles.xml"), donor.read("xl/styles.xml"))
        sheet = xml(donor.read(donor_sheet))
        for cell in sheet.iter(f"{{{S}}}c"):
            if cell.get("s") is not None:
                cell.set("s", str(style_ids[int(cell.get("s"))]))
        changes = {target: serialize(sheet), "xl/styles.xml": styles}
        additions = {}
        paths = {donor_sheet: target}

        def copy_relationships(source_part, output_part):
            rel_path = rels_part(source_part)
            if rel_path not in donor.namelist():
                return
            relationships = xml(donor.read(rel_path))
            for relation in relationships:
                if relation.get("TargetMode") == "External":
                    raise ValueError(f"generated {sheet_name} sheet must not introduce external relationships")
                source = resolve_part(source_part, relation.get("Target"))
                if source not in paths:
                    folder, name = posixpath.split(source)
                    result = posixpath.join(folder, "till-" + sheet_name.lower() + "-" + name)
                    stem, suffix = posixpath.splitext(result)
                    number = 2
                    while result in original.namelist() or result in additions:
                        result = f"{stem}-{number}{suffix}"
                        number += 1
                    paths[source] = result
                    additions[result] = donor.read(source)
                    copy_relationships(source, result)
                relation.set("Target", posixpath.relpath(paths[source], posixpath.dirname(output_part)))
            additions[rels_part(output_part)] = serialize(relationships)

        copy_relationships(donor_sheet, target)
        original_rels = rels_part(target)
        if original_rels in original.namelist() and original_rels not in additions:
            changes[original_rels] = serialize(ET.Element(f"{{{P}}}Relationships", nsmap={None: P}))
        workbook = xml(original.read("xl/workbook.xml"))
        names = workbook.find(f"{{{S}}}definedNames")
        if names is None:
            names = ET.Element(f"{{{S}}}definedNames")
            workbook.insert(list(workbook).index(workbook.find(f"{{{S}}}sheets")) + 1, names)
        for name in list(names):
            if name.get("localSheetId") == str(index) and name.get("name") in {
                    "_xlnm.Print_Area", "_xlnm.Print_Titles"}:
                names.remove(name)
        donor_names = xml(donor.read("xl/workbook.xml")).find(f"{{{S}}}definedNames")
        if donor_names is not None:
            for name in donor_names:
                node = copy.deepcopy(name)
                node.set("localSheetId", str(index))
                names.append(node)
        changes["xl/workbook.xml"] = serialize(workbook)
        types = xml(original.read("[Content_Types].xml"))
        existing_defaults = {node.get("Extension"): node.get("ContentType") for node in types
                             if node.tag.endswith("Default")}
        for node in xml(donor.read("[Content_Types].xml")):
            if node.tag.endswith("Default"):
                extension = node.get("Extension")
                if extension in existing_defaults and existing_defaults[extension] != node.get("ContentType"):
                    raise ValueError(f"content-type conflict for {extension}")
                if extension not in existing_defaults:
                    types.append(copy.deepcopy(node))
            elif node.get("PartName", "").lstrip("/") in paths:
                source = node.get("PartName").lstrip("/")
                if source != donor_sheet:
                    new_node = copy.deepcopy(node)
                    new_node.set("PartName", "/" + paths[source])
                    types.append(new_node)
        changes["[Content_Types].xml"] = serialize(types)
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as output:
            output.comment = original.comment
            for entry in original.infolist():
                output.writestr(entry, changes.get(entry.filename, additions.pop(
                    entry.filename, original.read(entry.filename))))
            for name, content in additions.items():
                output.writestr(name, content)


def validate_package(binder, output, coordinates, images, with_photos, deli_coordinates=None):
    file_size = output.stat().st_size
    if with_photos and file_size > MAX_GITHUB_FILE_SIZE:
        raise ValueError(f"{output}: photo workbook exceeds the 100 MiB GitHub file-size limit")
    with zipfile.ZipFile(binder) as original, zipfile.ZipFile(output) as generated:
        if generated.testzip() is not None:
            raise ValueError(f"{output}: ZIP checksum failure")
        target, index = sheet_info(original)
        allowed = {target, rels_part(target), "xl/styles.xml", "xl/workbook.xml", "[Content_Types].xml"}
        replaced_indexes = {index}
        if deli_coordinates is not None:
            deli_target, deli_index = sheet_info(original, "Deli")
            allowed.update({deli_target, rels_part(deli_target)})
            replaced_indexes.add(deli_index)
        preserved = []
        for name in original.namelist():
            unchanged = original.read(name) == generated.read(name)
            preserved.append(dict(part=name, sha256_before=sha(original.read(name)),
                                  sha256_after=sha(generated.read(name)), byte_identical=unchanged))
            if name not in allowed and not unchanged:
                raise ValueError(f"unrelated workbook part changed: {name}")
        for name in ("xl/workbook.xml",):
            before, after = xml(original.read(name)), xml(generated.read(name))
            for tree in (before, after):
                names = tree.find(f"{{{S}}}definedNames")
                if names is not None:
                    for node in list(names):
                        if node.get("localSheetId") in {str(i) for i in replaced_indexes} and node.get("name") in {
                                "_xlnm.Print_Area", "_xlnm.Print_Titles"}:
                            names.remove(node)
                    if not len(names):
                        tree.remove(names)
            if ET.tostring(before, method="c14n") != ET.tostring(after, method="c14n"):
                raise ValueError("unrelated workbook settings changed")
        before, after = xml(original.read("xl/styles.xml")), xml(generated.read("xl/styles.xml"))
        for group in before:
            other = after.find(group.tag)
            if other is None or len(other) < len(group):
                raise ValueError("existing workbook style collection lost")
            for a, b in zip(group, other):
                if ET.tostring(a, method="c14n") != ET.tostring(b, method="c14n"):
                    raise ValueError("an existing workbook style changed")
        # Every internal relationship must still point at an actual package member.
        for name in generated.namelist():
            if not name.endswith(".rels"):
                continue
            part = posixpath.join(posixpath.dirname(posixpath.dirname(name)),
                                  posixpath.basename(name)[:-5])
            if name == "_rels/.rels":
                part = ""
            for relation in xml(generated.read(name)):
                if relation.get("TargetMode") != "External":
                    resolved = resolve_part(part, relation.get("Target"))
                    if resolved not in generated.namelist():
                        raise ValueError(f"broken relationship: {name} -> {resolved}")
    workbook = load_workbook(output)
    original_book = load_workbook(binder, read_only=True)
    try:
        if workbook.sheetnames != original_book.sheetnames:
            raise ValueError("worksheet names or order changed")
        if deli_coordinates is not None:
            validate_deli_sheet(workbook["Deli"], deli_coordinates)
        sheet = workbook["Produce"]
        for entry in coordinates:
            code, description = sheet[entry["code_cell"]], sheet[entry["description_cell"]]
            if code.value != entry["plu"] or code.data_type != "s" or code.number_format != "@":
                raise ValueError(f"{entry['code_cell']}: code is not exact source text")
            if description.value != entry["product"] or description.data_type != "s":
                raise ValueError(f"{entry['description_cell']}: description changed or truncated")
            if entry["duplicate_count"] > 1 and code.fill.fgColor.rgb != "00FFC7CE":
                raise ValueError("duplicate PLU warning absent")
            if sheet[entry["image_cell"]].value is not None:
                raise ValueError("image/source labels must not appear in cashier binder cells")
        embedded = sheet._images
        expected = {entry["image_cell"]: images[entry["source_id"]] for entry in coordinates
                    if with_photos and entry["source_id"] in images}
        if len(embedded) != len(expected):
            raise ValueError("Produce image count differs from mapped references")
        for picture in embedded:
            from openpyxl.utils import get_column_letter
            anchor = picture.anchor._from
            coordinate = get_column_letter(anchor.col + 1) + str(anchor.row + 1)
            if coordinate not in expected or sha(picture._data()) != sha(expected.pop(coordinate)):
                raise ValueError("embedded image content/anchor differs from mapping")
        if expected:
            raise ValueError("mapped image missing from Produce sheet")
        return dict(
            status="PASS", original_sheet_names=original_book.sheetnames,
            worksheets_preserved=len(workbook.sheetnames), produce_records_verified=len(coordinates),
            deli_records_verified=len(deli_coordinates) if deli_coordinates is not None else 0,
            produce_images_verified=len(embedded), original_parts_checked=len(preserved),
            original_parts_byte_identical=sum(row["byte_identical"] for row in preserved),
            unrelated_package_parts_byte_identical=True, existing_styles_preserved=True,
            unrelated_workbook_settings_preserved=True, internal_relationships_valid=True,
            exact_text_codes_and_descriptions=True, duplicate_highlights_verified=True,
            file_sha256=sha(output.read_bytes()), file_size_bytes=file_size, package_parts=preserved,
        )
    finally:
        workbook.close()
        original_book.close()


def validate_print(output, coordinates, expected_pages, deli_coordinates=None, deli_title=None,
                   bulk_pages=None):
    from pypdf import PdfReader

    if not shutil.which("soffice"):
        raise ValueError("print validation requires LibreOffice Calc (soffice)")
    result = {}
    with tempfile.TemporaryDirectory(prefix="till-print-") as directory:
        work = Path(directory)
        command = [
            "soffice", "-env:UserInstallation=" + (work / "profile").as_uri(),
            "--headless", "--convert-to", "pdf", "--outdir", str(work),
            *[str((output / filename).resolve()) for filename in FILENAMES.values()],
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=300, check=True)
        (output / "PRINT_ENGINE_LOG.txt").write_text(process.stdout + process.stderr, encoding="utf-8")
        for edition, filename in FILENAMES.items():
            complete = work / (Path(filename).stem + ".pdf")
            if not complete.is_file():
                raise ValueError("Calc did not open/export the complete binder; check PRINT_ENGINE_LOG.txt "
                                 "and install libreoffice-calc")
            full_pdf = PdfReader(complete)
            if bulk_pages:
                all_codes = set().union(*(page["codes"] for page in bulk_pages))
                matches = []
                for expected in bulk_pages:
                    found = []
                    for number, page in enumerate(full_pdf.pages):
                        text = " ".join((page.extract_text() or "").split())
                        printed = Counter(word for word in text.split() if word in all_codes)
                        if expected["heading"] in text and printed == expected["codes"]:
                            found.append(number)
                    if len(found) != 1:
                        raise ValueError(f"{edition}: Bulk section {expected['heading']!r} "
                                         "does not print exactly once with its original PLUs")
                    page = full_pdf.pages[found[0]]
                    if abs(float(page.mediabox.width) - 792) > 1 or abs(float(page.mediabox.height) - 612) > 1:
                        raise ValueError(f"{edition}: Bulk is not landscape US Letter")
                    matches.append(found[0])
                if matches != list(range(matches[0], matches[0] + len(matches))):
                    raise ValueError(f"{edition}: Bulk sections are not on consecutive pages")
            if deli_coordinates is not None:
                deli_pages = [page for page in full_pdf.pages
                              if " ".join(deli_title.split()) in " ".join(page.extract_text().split())]
                if len(deli_pages) != 1:
                    raise ValueError(f"{edition}: updated Deli must print on exactly one page")
                deli_page = deli_pages[0]
                if abs(float(deli_page.mediabox.width) - 612) > 1 or abs(float(deli_page.mediabox.height) - 792) > 1:
                    raise ValueError(f"{edition}: Deli is not portrait US Letter")
                deli_text = " ".join(deli_page.extract_text().split())
                codes = Counter(entry["plu"] for entry in deli_coordinates)
                printed = Counter(word for word in deli_text.split() if word in codes)
                if printed != codes:
                    raise ValueError(f"{edition}: printed deli PLUs missing or duplicated")
                if any(" ".join(entry["product"].split()) not in deli_text for entry in deli_coordinates):
                    raise ValueError(f"{edition}: printed deli products missing or clipped")
            shutil.copyfile(complete, output / complete.name)
            produce_pages = [page for page in full_pdf.pages if
                             "PRODUCE PLU QUICK GUIDE" in page.extract_text()]
            if len(produce_pages) != expected_pages:
                raise ValueError(f"{edition}: expected {expected_pages} Produce pages; got {len(produce_pages)}")
            all_codes = {entry["plu"] for entry in coordinates}
            total_drawn = 0
            for number, page in enumerate(produce_pages, 1):
                if abs(float(page.mediabox.width) - 792) > 1 or abs(float(page.mediabox.height) - 612) > 1:
                    raise ValueError(f"{edition} page {number}: not landscape US Letter")
                text = page.extract_text()
                selected = [entry for entry in coordinates if entry["page"] == number]
                codes = Counter(entry["plu"] for entry in selected)
                codes.update(word for entry in selected for word in entry["product"].split()
                             if word in all_codes)
                printed = Counter(word for word in text.split() if word in all_codes)
                if printed != codes:
                    raise ValueError(f"{edition} page {number}: printed codes missing, duplicated or clipped: "
                                     f"missing {codes - printed}; unexpected {printed - codes}")
                normalized = " ".join(text.split())
                missing = [entry["product"] for entry in selected
                           if " ".join(entry["product"].split()) not in normalized]
                if missing:
                    raise ValueError(f"{edition} page {number}: missing/clipped descriptions: {missing}")
                resources = page["/Resources"]["/XObject"] if "/XObject" in page["/Resources"] else {}
                drawn = sum(
                    resources[operands[0]].get_object().get("/Subtype") == "/Image"
                    for operands, operator in page.get_contents().operations if operator == b"Do"
                )
                total_drawn += drawn
            result[edition] = dict(
                status="PASS", pages=len(produce_pages), landscape_us_letter=True,
                complete_workbook_opened_and_exported_by_calc=True,
                complete_binder_pdf_pages=len(full_pdf.pages),
                every_page_code_count_verified=True, every_description_found=True,
                drawn_images=total_drawn,
                deli_print_records_verified=len(deli_coordinates) if deli_coordinates is not None else 0,
                bulk_print_pages_verified=len(bulk_pages) if bulk_pages else 0,
                complete_pdf=complete.name,
                visual_review="REQUIRED; automated text/geometry checks are not a visual print approval",
            )
    return result


def bulk_print_pages(path):
    workbook = load_workbook(path, read_only=False)
    try:
        if "Bulk" not in workbook:
            return None
        sheet = workbook["Bulk"]
        breaks = [item.id for item in sheet.row_breaks.brk if item.man]
        if len(breaks) != 3:
            return None
        area = sheet.print_area
        if not area or "," in area or "!" not in area:
            raise ValueError("combined Bulk must have one print area")
        _, min_row, _, max_row = range_boundaries(area.split("!", 1)[1].replace("$", ""))
        boundaries = [min_row, *(number + 1 for number in breaks), max_row + 1]
        if boundaries != sorted(set(boundaries)):
            raise ValueError("invalid combined Bulk page breaks")
        pages = []
        for start, end in zip(boundaries, boundaries[1:]):
            heading = sheet.cell(start, 2).value
            if not isinstance(heading, str) or not heading.strip():
                raise ValueError("combined Bulk page must start with a section heading in column B")
            codes = Counter(str(sheet.cell(row, col).value) for row in range(start, end)
                            for col in (3, 6, 9) if sheet.cell(row, col).value is not None)
            pages.append(dict(heading=" ".join(heading.split()), codes=codes))
        return pages
    finally:
        workbook.close()


def report_text(summary):
    lines = [
        "PRODUCE TILL BINDER - CHANGE AND VALIDATION REPORT",
        "REVIEW COPY ONLY - NOT RELEASED FOR OPERATIONAL TILL USE",
        "",
        f"Source XML SHA-256: {summary['picklist_sha256']}",
        f"Original workbook SHA-256: {summary['original_binder_sha256']}",
        f"Updated Deli source SHA-256: {summary['deli_source_sha256']}; "
        f"entries: {summary['deli_records_included']}",
        f"XML records: {summary['total_source_records']}; active: {summary['active_source_records']}; "
        f"hidden/deleted: {summary['hidden_or_deleted_records']}",
        f"Produce included: {summary['produce_records_included']}; "
        f"unique PLUs: {summary['unique_produce_plus']}; duplicate codes: {summary['duplicate_produce_codes']}",
        f"Known non-produce records excluded from Produce: "
        f"{summary['known_non_produce_excluded']}",
        f"Original Produce entries compared: {summary['original_produce_entries']}",
        f"Embedded supplied references: {summary['embedded_references']}; "
        f"missing/uncertain images left blank: {summary['missing_or_uncertain_images']}",
        f"AI illustrations included as visual references: {summary['ai_illustrations_embedded']}",
        f"New owner-supplied AI crops: {summary['new_ai_crops_embedded']}",
        f"AI illustrations omitted (if rejected or invalid association): {summary['ai_illustrations_omitted']}",
        f"Classification review: {summary['classification_review_required']}; "
        f"organic placement review: {summary['placement_review_required']}",
        "",
        "When present, the four original Bulk sheets are combined, with a print break between sections.",
        "Every original package part outside the Produce, Deli and combined Bulk sheets, their relationships,",
        "append-only styles, content types and their print names is byte-identical. No original part is removed.",
        "Existing styles and all unrelated workbook-level settings are independently compared.",
        "PLU/description strings, duplicate highlights and embedded image bytes/anchors are verified.",
        "Cashier sheets have no image/source/review labels. The organic badge remains.",
        "",
        "Original-sheet comparison outcomes (no uncertain mapping silently resolved):",
        *[f"  {key}: {value}" for key, value in summary["original_comparison_counts"].items()],
        "",
        "Image outcomes:",
        *[f"  {key}: {value}" for key, value in summary["image_status_counts"].items()],
        "",
        f"Print validation: {json.dumps(summary['print_validation'])}",
        "",
        "Detailed reports:",
        "  VALIDATION.json: checks, hashes, counts and publication blockers",
        "  DELI_LAYOUT.csv: exact owner-supplied deli names, PLUs and two-column cell locations",
        "  ORIGINAL_PRODUCE_CHANGES.csv: every original entry and current-source candidates",
        "  UPDATED_PRODUCE_RECORDS.csv: every included source record versus the original sheet",
        "  DUPLICATE_PLU_RECORDS.csv: all included records with ambiguous/repeated codes",
        "  ACTIVE_SOURCE_DUPLICATES.csv: every active source record sharing a code, including non-produce",
        "  EXCLUDED_RECORDS.csv: hidden/deleted and known non-produce exclusions",
        "  PHOTO_MAPPING.csv: per-record source, image status, dimensions, hashes and missing-image reasons",
        "  MISSING_IMAGES.csv: remaining blank Produce entries",
        "  AI_REFERENCE_REVIEW.csv: exact identities, crop boxes and excluded AI panels",
        "  PRODUCE_LAYOUT.csv: exact record-to-cell and printed-page mapping for both editions",
        "  PLACEMENT_REVIEW.csv: unresolved classifications/counterparts",
        "  PACKAGE_PRESERVATION_PHOTOS.csv: before/after package hashes",
        "  reconciliation/: full authoritative XML catalogue and existing production-readiness gates",
        "  REGENERATE.txt: exact command with original input paths (choose a new empty output directory)",
        "",
        "Unresolved issues / limits:",
        *["  " + item for item in summary["limitations"]],
        "",
        "No original file, authoritative XML, assignment approval or published booklet was changed.",
    ]
    return "\n".join(lines) + "\n"


def generate(root, binder, output, verify_print=False):
    if not binder.is_file():
        raise ValueError(f"missing original till binder: {binder}")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output must be empty; the original and previous outputs are never overwritten")
    original_checksum = sha(binder.read_bytes())
    deli_document = root / "sources/binders/Deli.docx"
    deli_document_checksum = sha(deli_document.read_bytes())
    deli_content, deli_coordinates = read_deli_source(root)
    deli_checksum = sha(deli_content)
    deli_workbook = load_workbook(io.BytesIO(deli_content), read_only=True)
    try:
        deli_title = deli_workbook["Deli"]["A1"].value
    finally:
        deli_workbook.close()
    with zipfile.ZipFile(binder) as original:
        sheet_info(original, "Deli")
    source_items, digest = read_picklist(root / "sources/plu/PickList.xml")
    assignments = read_assignments(root / "data/picklist_assignments.json")
    reconciliation = output / "reconciliation"
    reconciliation.mkdir()
    _, _, _, source_summary = reconcile(root, reconciliation)
    items, working_digest = read_working_list(root)
    if working_digest != digest:
        raise ValueError("WorkingList reconciliation used a different PickList version")
    rows, exclusions = produce_catalog(items, assignments)
    if not rows:
        raise ValueError("no visible Produce records to generate")
    if any(not row["name"].strip() for row in rows):
        raise ValueError("source contains blank Produce descriptions; refusing an unusable quick guide")
    visuals = visual_records(root)
    images, image_report = map_images(root, rows, assignments, visuals)
    photo_images = {source_id: workbook_photo_copy(content) for source_id, content in images.items()}
    for record in image_report:
        if record["source_id"] in photo_images:
            record["embedded_sha256"] = sha(photo_images[record["source_id"]])
    _, reference_audit = load_references(root, rows)
    csv_output(output / "AI_REFERENCE_REVIEW.csv", reference_audit, [
        "source_id", "source_identity_ids", "plu", "product", "decision", "status", "source_document",
        "source_sha256", "source_member", "crop_box", "crop_sha256", "width", "height",
        "image_source", "rights_status", "details",
    ])
    old = old_entries(binder)
    changes, additions = comparisons(old, items, rows)
    validations, coordinates = {}, None
    for edition, filename in FILENAMES.items():
        edition_images = photo_images if edition == "photos" else images
        donor, edition_coordinates, pages = quick_sheet(rows, edition_images, edition == "photos")
        if coordinates is not None and edition_coordinates != coordinates:
            raise ValueError("text and photo editions have different data/layout")
        coordinates = edition_coordinates
        path = output / filename
        with tempfile.TemporaryDirectory(prefix="till-produce-") as temporary:
            bulk_binder = Path(temporary) / "Bulk.xlsx"
            produce_binder = Path(temporary) / "Produce.xlsx"
            bulk_combined = combine_bulk(binder, bulk_binder)
            replace_produce(bulk_binder, donor, produce_binder)
            replace_sheet(produce_binder, deli_content, path, "Deli")
            validations[edition] = validate_package(
                bulk_binder, path, coordinates, edition_images, edition == "photos", deli_coordinates)
        if bulk_combined and bulk_print_pages(path) is None:
            raise ValueError("combined Bulk is missing its three page breaks")
        validations[edition]["bulk_sheets_combined"] = bulk_combined
        parts = validations[edition].pop("package_parts")
        if bulk_combined:
            with zipfile.ZipFile(binder) as original, zipfile.ZipFile(path) as generated:
                bulk_part, _ = sheet_info(original, "Bulk")
                validations[edition]["output_sheet_names"] = validations[edition]["original_sheet_names"]
                validations[edition]["original_sheet_names"] = [
                    sheet.get("name") for sheet in xml(original.read("xl/workbook.xml")).find(f"{{{S}}}sheets")
                ]
                for part in parts:
                    name = part["part"]
                    before, after = original.read(name), generated.read(name)
                    part.update(sha256_before=sha(before), sha256_after=sha(after),
                                byte_identical=before == after)
                    if name not in {bulk_part, "xl/workbook.xml"} and name not in {
                            sheet_info(original, "Produce")[0], rels_part(sheet_info(original, "Produce")[0]),
                            sheet_info(original, "Deli")[0], rels_part(sheet_info(original, "Deli")[0]),
                            "xl/styles.xml", "[Content_Types].xml"} and before != after:
                        raise ValueError(f"unrelated workbook part changed: {name}")
            validations[edition]["original_parts_byte_identical"] = sum(row["byte_identical"] for row in parts)
        csv_output(output / f"PACKAGE_PRESERVATION_{edition.upper()}.csv", parts,
                   ["part", "sha256_before", "sha256_after", "byte_identical"])
    csv_output(output / "PRODUCE_LAYOUT.csv", coordinates,
               ["source_id", "plu", "product", "code_cell", "description_cell", "image_cell", "page", "duplicate_count"])
    csv_output(output / "DELI_LAYOUT.csv", deli_coordinates,
               ["category", "product", "plu", "product_cell", "code_cell"])
    csv_output(output / "PHOTO_MAPPING.csv", image_report, [
        "source_id", "source_identity_ids", "plu", "product", "image_status", "embedded", "image_source",
        "source_document", "source_member", "original_sha256", "embedded_sha256",
        "width", "height", "visual_verdict", "visual_review_note", "image_approval_status",
        "approval_basis", "legacy_entry_idx", "legacy_original_verdict",
        "rights_status", "photograph_status",
        "organic_badge", "reused_by_entries", "details",
    ])
    csv_output(output / "ORIGINAL_PRODUCE_CHANGES.csv", changes, [
        "cell", "original_code", "original_description", "heading", "issue", "status",
        "active_match_count", "candidate_source_ids", "current_codes", "current_descriptions",
    ])
    csv_output(output / "UPDATED_PRODUCE_RECORDS.csv", additions, ["source_id", "plu", "product", "status"])
    csv_output(output / "EXCLUDED_RECORDS.csv", exclusions,
               ["source_id", "source_position", "plu", "name", "visible", "deleted", "reason"])
    duplicates = [dict(row) for row in rows if row["duplicate_count"] > 1]
    csv_output(output / "DUPLICATE_PLU_RECORDS.csv", duplicates,
               ["source_id", "source_ids", "plu", "name", "duplicate_count", "source_position"])
    active_source_code_counts = Counter(item["plu"] for item in source_items if item["included"])
    csv_output(output / "ACTIVE_SOURCE_DUPLICATES.csv", [
        dict(item, active_code_count=active_source_code_counts[item["plu"]])
        for item in source_items if item["included"] and active_source_code_counts[item["plu"]] > 1
    ], ["source_id", "source_position", "plu", "name", "department", "active_code_count"])
    csv_output(output / "PLACEMENT_REVIEW.csv",
               [row for row in rows if row["placement_status"] == "PLACEMENT_REVIEW_REQUIRED" or
                row["classification_status"] != "EXISTING_CLASSIFICATION"],
               ["source_id", "plu", "name", "display_section", "classification_status",
                "placement_status", "counterpart_source_ids", "placement_note"])
    summary = dict(
        status="REVIEW_ONLY_NOT_RELEASED", production_publication="BLOCKED",
        original_binder=str(binder), original_binder_sha256=original_checksum,
        deli_source=str(root / DELI_SOURCE), deli_source_sha256=deli_checksum,
        deli_original_document_sha256=deli_document_checksum,
        deli_records_included=len(deli_coordinates),
        picklist_sha256=digest, total_source_records=len(source_items),
        active_source_records=sum(item["included"] for item in source_items),
        hidden_or_deleted_records=sum(not item["included"] for item in source_items),
        known_non_produce_excluded=sum(row["reason"] == "NON_PRODUCE_IN_OTHER_BINDER_SECTIONS" for row in exclusions),
        produce_records_included=len(rows), unique_produce_plus=len({row["plu"] for row in rows}),
        duplicate_produce_codes=len({row["plu"] for row in duplicates}),
        duplicate_produce_records=len(duplicates), original_produce_entries=len(old),
        original_comparison_counts=dict(Counter(row["status"] for row in changes)),
        updated_record_counts=dict(Counter(row["status"] for row in additions)),
        image_status_counts=dict(Counter(row["image_status"] for row in image_report)),
        embedded_references=len(images), missing_or_uncertain_images=len(rows) - len(images),
        ai_illustrations_embedded=sum(row["image_source"] == "AI Generated" and row["embedded"]
                                      for row in image_report),
        ai_illustrations_omitted=sum(row["image_source"] == "AI Generated" and not row["embedded"]
                                     for row in image_report),
        new_ai_crops_embedded=sum(row["image_status"] == "SUPPLIED_AI_CROP_REVIEW" for row in image_report),
        classification_review_required=sum(row["classification_status"] != "EXISTING_CLASSIFICATION" for row in rows),
        placement_review_required=sum(row["placement_status"] == "PLACEMENT_REVIEW_REQUIRED" for row in rows),
        planned_produce_print_pages=pages,         source_reconciliation=source_summary,
        working_list_reconciliation=json.loads(
            (reconciliation / "WORKING_LIST_RECONCILIATION.json").read_text(encoding="utf-8")),
        validations=validations, print_validation="NOT_RUN",
        limitations=[
            "The complete binder is a REVIEW copy, not approved for operational till use.",
            "Legacy images are pre-approved by owner policy; source, historical verdict, rights and provenance "
            "remain documented in the external audit report.",
            "Missing, identity-mismatched, checksum-changed and unreadable image associations remain blank.",
            "Existing and newly supplied identity-linked AI illustrations are visual references at the owner's request; "
            "AI provenance and uncertain visual verdicts are recorded only in the external audit report.",
            "Old descriptions are contextual abbreviations; code-only/name-only differences are not automatic corrections.",
            "Deli is replaced from the owner-supplied two-column source; Bulk sections are combined "
            "with page breaks; all other unrelated operational sheets remain unchanged.",
            "Future unclassified entries are retained for review, not silently discarded or approved.",
        ],
    )
    csv_output(output / "MISSING_IMAGES.csv", [row for row in image_report if not row["embedded"]], [
        "source_id", "plu", "product", "image_status", "visual_review_note", "details",
    ])
    if sha(binder.read_bytes()) != original_checksum or sha(
            (root / "sources/plu/PickList.xml").read_bytes()) != digest:
        raise ValueError("an input changed during generation; discard outputs and retry")
    (output / "VALIDATION.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output / "PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt").write_text(report_text(summary), encoding="utf-8")
    if verify_print:
        summary["print_validation"] = validate_print(
            output, coordinates, pages, deli_coordinates=deli_coordinates, deli_title=deli_title,
            bulk_pages=bulk_print_pages(output / FILENAMES["photos"]))
        if summary["print_validation"]["photos"]["drawn_images"] != len(images):
            raise ValueError("printed reference count differs from the exact image mapping")
        (output / "VALIDATION.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (output / "PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt").write_text(report_text(summary), encoding="utf-8")
    if sha(binder.read_bytes()) != original_checksum or sha(
            (root / "sources/plu/PickList.xml").read_bytes()) != digest:
        raise ValueError("an input changed during print validation; discard outputs and retry")
    if (sha((root / DELI_SOURCE).read_bytes()) != deli_checksum or
            sha(deli_document.read_bytes()) != deli_document_checksum):
        raise ValueError("deli source changed during generation; discard outputs and retry")
    command = [sys.executable, str((ROOT / "tools/build_till_binders.py").resolve()),
               "--root", str(root.resolve()), "--binder", str(binder.resolve()),
               "--output", str(output.resolve())]
    if verify_print:
        command.append("--verify-print")
    (output / "REGENERATE.txt").write_text(
        "Exact generation command (output must be empty; use a new directory when rerunning):\n\n" +
        shlex.join(command) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--binder", type=Path, required=True, help="Complete binder template (never modified)")
    parser.add_argument("--output", type=Path, required=True, help="Empty directory for the review binder and reports")
    parser.add_argument("--verify-print", action="store_true",
                        help="Export the complete binder PDF and verify printed Produce and Deli records")
    args = parser.parse_args()
    try:
        summary = generate(args.root, args.binder, args.output, args.verify_print)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.XMLSyntaxError,
            subprocess.SubprocessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps({key: summary[key] for key in (
        "status", "produce_records_included", "embedded_references", "missing_or_uncertain_images",
        "duplicate_produce_codes", "planned_produce_print_pages")}, indent=2))


if __name__ == "__main__":
    main()
