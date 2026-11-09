"""Reconcile current XML with reviewed assets; build only when every requirement passes."""
import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageOps

from check_image_uniqueness import image_fingerprint
from organic_watermarks import badge_artwork, render_watermark
from picklist_catalog import read_assignments, read_picklist

ROOT = Path(__file__).resolve().parents[1]
BOOKS = {"Fruit": "FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION",
         "Vegetable": "VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION",
         "Non-produce": "NON_PRODUCE_PLU_CASHIER_BOOKLET"}


def organic(item):
    return bool(re.search(r"\borganic\b", item["name"], re.I))


def safe_asset(root, name):
    if not isinstance(name, str) or not name:
        raise ValueError("missing asset path")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or out-of-repository asset: {name}")
    return path


def original_image(root, assignment):
    record = assignment.get("legacy_organic_original")
    if record:
        from organic_watermarks import original_content
        return original_content(dict(record, idx=assignment["source_id"]), root)
    return safe_asset(root, assignment["image"]).read_bytes()


def reviewed_image(root, item, assignment):
    from verify_images import LICENSES

    content = original_image(root, assignment)
    errors = []
    with Image.open(io.BytesIO(content)) as image:
        if getattr(image, "n_frames", 1) != 1:
            errors.append("MULTIFRAME_IMAGE")
        image.load()
        width, height = ImageOps.exif_transpose(image).size
    if min(width, height) < 500:
        errors.append("BELOW_500_PX")
    if assignment.get("visual_approval_status") != "APPROVED":
        errors.append("VISUAL_APPROVAL_REQUIRED")
    if assignment.get("photographic_origin") != "VERIFIED_PHOTO":
        errors.append("PHOTOGRAPHIC_ORIGIN_NOT_VERIFIED")
    if assignment.get("rights_verification_status") != "VERIFIED":
        errors.append("IMAGE_RIGHTS_NOT_VERIFIED")
    if assignment.get("image_sha256") != hashlib.sha256(content).hexdigest():
        errors.append("IMAGE_CHECKSUM_MISMATCH")
    if (assignment.get("reviewed_plu"), assignment.get("reviewed_product")) != (
            item["plu"], item["name"]):
        errors.append("PRODUCT_IMAGE_REVIEW_REQUIRED")
    provenance = assignment.get("provenance", {})
    if provenance.get("license") not in LICENSES:
        errors.append("SUPPORTED_IMAGE_LICENCE_REQUIRED")
    for key in ("creator", "license_url", "source_page_url", "original_image_url",
                "attribution", "changes", "rights_evidence"):
        if not isinstance(provenance.get(key), str) or not provenance[key].strip():
            errors.append("MISSING_PROVENANCE_" + key.upper())
    return content, width, height, errors


def csv_output(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def reconcile(root, output):
    items, digest = read_picklist(root / "sources/plu/PickList.xml")
    assignments = read_assignments(root / "data/picklist_assignments.json")
    rows, requests, all_image_requests, images, groups = [], [], [], {}, defaultdict(list)
    active_ids = set()
    for item in items:
        if not item["included"]:
            continue
        active_ids.add(item["source_id"])
        assignment = assignments.get(item["source_id"])
        errors = []
        row = dict(item, book=assignment["book"] if assignment else "",
                   section=assignment.get("section", "") if assignment else "",
                   image=assignment.get("image", "") if assignment else "",
                   organic=organic(item), width=0, height=0)
        if not assignment:
            errors.extend(["CLASSIFICATION_REQUIRED", "APPROVED_IMAGE_REQUIRED"])
        elif assignment["book"] == "Non-produce" and assignment.get("image_mode") == "CODE_ONLY":
            if assignment.get("code_only_approved") is not True:
                errors.append("CODE_ONLY_APPROVAL_REQUIRED")
            if (assignment.get("reviewed_plu"), assignment.get("reviewed_product")) != (
                    item["plu"], item["name"]):
                errors.append("CODE_ONLY_PRODUCT_REVIEW_REQUIRED")
        elif not assignment.get("image"):
            errors.append("APPROVED_IMAGE_REQUIRED")
        else:
            try:
                content, width, height, image_errors = reviewed_image(root, item, assignment)
                errors.extend(image_errors)
                row.update(width=width, height=height)
                images[item["source_id"]] = content
                groups[image_fingerprint(io.BytesIO(content))].append(row)
            except (OSError, ValueError, KeyError) as exc:
                errors.append("INVALID_IMAGE: " + str(exc))
        if not row["section"]:
            errors.append("SECTION_REQUIRED")
        row["blockers"] = errors
        rows.append(row)
        request = dict(
            idx=str(item["source_position"]), source_id=item["source_id"],
            plu=item["plu"], name=item["name"], query=search_query(item["name"]),
        )
        approved_code_only = (assignment and assignment["book"] == "Non-produce" and
                              assignment.get("image_mode") == "CODE_ONLY" and
                              assignment.get("code_only_approved") is True and
                              (assignment.get("reviewed_plu"), assignment.get("reviewed_product")) ==
                              (item["plu"], item["name"]))
        if not approved_code_only:
            all_image_requests.append(request)
        if not assignment or not assignment.get("image") and assignment.get("image_mode") != "CODE_ONLY":
            requests.append(request)
    for group in groups.values():
        if len(group) < 2:
            continue
        conventional = [row for row in group if not row["organic"]]
        permitted = len(conventional) == 1 and all(
            row["book"] == conventional[0]["book"] and
            assignments[row["source_id"]].get("reuse_from_source_id") == conventional[0]["source_id"]
            for row in group if row["organic"])
        if not permitted:
            for row in group:
                row["blockers"].append("PROHIBITED_IMAGE_REUSE")
    if not rows:
        raise ValueError("PickList has no visible, non-deleted products; nothing to publish")
    presentation = booklet_order(rows, assignments)
    inactive = [dict(source_id=key, book=value["book"],
                     reviewed_plu=value.get("reviewed_plu", ""),
                     reviewed_product=value.get("reviewed_product", ""))
                for key, value in assignments.items() if key not in active_ids]
    fields = ["source_id", "source_position", "occurrence", "plu", "name", "department",
              "visible", "deleted", "included", "picture_references"]
    csv_output(output / "PICKLIST_CATALOG.csv", items, fields)
    csv_output(output / "PICKLIST_SYNC.csv",
               [dict(row, blockers="; ".join(row["blockers"])) for row in rows],
               fields + ["book", "section", "image", "organic", "width", "height", "blockers"])
    csv_output(output / "IMAGE_REQUESTS.csv", requests,
               ["idx", "source_id", "plu", "name", "query"])
    csv_output(output / "ALL_IMAGE_REQUESTS.csv", all_image_requests,
               ["idx", "source_id", "plu", "name", "query"])
    csv_output(output / "INACTIVE_ASSIGNMENTS.csv", inactive,
               ["source_id", "book", "reviewed_plu", "reviewed_product"])
    csv_output(output / "BOOKLET_ORDER.csv", presentation,
               ["book", "booklet_position", "source_id", "source_position", "plu", "name",
                "display_section", "placement_status", "counterpart_source_ids", "placement_note"])
    summary = dict(
        source="sources/plu/PickList.xml", source_sha256=digest, source_unchanged=True,
        total_xml_records=len(items), included_records=len(rows),
        excluded_records=len(items) - len(rows),
        status="BLOCKED" if any(row["blockers"] for row in rows) else "READY_TO_BUILD",
        records_needing_review=sum(bool(row["blockers"]) for row in rows),
        missing_image_requests=len(requests), inactive_assignments=len(inactive),
        organic_placements_needing_review=sum(
            row["placement_status"] == "PLACEMENT_REVIEW_REQUIRED" for row in presentation),
        blocker_counts=dict(sorted(Counter(
            error for row in rows for error in row["blockers"]).items())),
    )
    (output / "PICKLIST_SYNC.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return rows, images, assignments, summary


def search_query(name):
    value = re.sub(r"\b(organic|small|large|medium)\b", "", name, flags=re.I)
    return " ".join(value.split()) or name


def placement_key(name):
    words = re.findall(r"[a-z0-9]+", name.lower())
    singulars = dict(apples="apple", pears="pear", grapes="grape", onions="onion",
                     peppers="pepper", tomatoes="tomato", potatoes="potato",
                     mushrooms="mushroom", oranges="orange", plums="plum",
                     nectarines="nectarine", peaches="peach", bananas="banana",
                     mangoes="mango", lemons="lemon", limes="lime", yams="yam")
    return tuple(sorted(singulars.get(word, word) for word in words
                        if word not in {"organic", "small", "medium", "large", "sml", "lrg"}))


def organic_display_section(row):
    if not re.search(r"\borganic\b", row["section"], re.I):
        return row["section"]
    families = {
        "Fruit": {
            "Apples": r"apple|apples|aples", "Pears": r"pear|pears", "Grapes": r"grape|grapes",
            "Berries": r"blueberries|strawberry|berries",
            "Citrus": r"grapefruit|grapefuit|shaddock|pommelo|orange|oranges|lemon|lemons|lime|limes|limequats|kumquat|buddha",
            "Melons": r"melon|watermelon|honeydew",
            "Stone Fruit": r"cherries|peach|peaches|nectarine|nectarines|plum|plums",
            "Tropical Fruit": r"avocado|banana|bananas|kiwi|mango|mangoes|pineapple",
            "Specialty Fruit": r"pomegranate|pomegrante",
        },
        "Vegetable": {
            "Brassicas": r"broccoli|broccolini|cabbage|cauliflower|romanesco",
            "Cucumbers": r"cucumber", "Lettuce": r"lettuce|lettuc",
            "Leafy Greens": r"chard|collard|mustard|kale|spinach",
            "Herbs": r"basil|chives|cilantro|dill|mint|parsley",
            "Onions": r"onion|onions|leeks|garlic", "Peppers": r"pepper|peppers",
            "Potatoes": r"potato|potatoes|yam|yams",
            "Root Vegetables": r"beet|beets|carrot|carrots|radish|ginger",
            "Squash": r"squash|zucchini", "Tomatoes": r"tomato|tomatoe|tomatoes",
            "Specialty Vegetables": r"beans|celery|eggplant|mushroom|mushrooms|okra|rhubarb",
        },
    }
    for section, pattern in families.get(row["book"], {}).items():
        if re.search(r"\b(?:" + pattern + r")\b", row["name"], re.I):
            return section
    return row["book"]


def booklet_order(rows, assignments):
    """Derive presentation only; never infer image approvals or rewrite source rows."""
    ordered = []
    for book in BOOKS:
        selected = [dict(row) for row in rows if row["book"] == book]
        if book == "Non-produce":
            ordered.extend(dict(row, display_section=row["section"], placement_status="SOURCE_ORDER",
                                counterpart_source_ids="", placement_note="") for row in selected)
            continue
        conventional, sections, descriptions = {}, {}, defaultdict(list)
        for row in selected:
            if not row["organic"]:
                key = (row["section"], placement_key(row["name"]))
                if key not in conventional:
                    descriptions[key[1]].append(key)
                conventional.setdefault(key, []).append(row)
                sections.setdefault(row["section"], None)
        by_id = {row["source_id"]: key for key, group in conventional.items() for row in group}
        paired, unmatched = defaultdict(list), defaultdict(list)
        for row in selected:
            if not row["organic"]:
                continue
            assignment = assignments.get(row["source_id"], {})
            reference = assignment.get("placement_after_source_id") or assignment.get("reuse_from_source_id")
            matches = descriptions.get(placement_key(row["name"]), [])
            key = matches[0] if len(matches) == 1 and matches[0][1] else None
            status = "MATCHED_DESCRIPTION"
            if reference:
                if reference not in by_id:
                    raise ValueError(f"{row['source_id']}: organic placement counterpart must be "
                                     "an included conventional entry in the same booklet")
                key = by_id[reference]
                status = "REVIEWED_COUNTERPART"
            group = conventional.get(key, [])
            if group:
                row.update(display_section=group[0]["section"], placement_status=status,
                           counterpart_source_ids=";".join(other["source_id"] for other in group),
                           placement_note="")
                paired[key].append(row)
            else:
                section = organic_display_section(row)
                sections.setdefault(section, None)
                note = ("Matching descriptions span multiple sections" if len(matches) > 1 else
                        "No clear conventional counterpart; review placement")
                row.update(display_section=section, placement_status="PLACEMENT_REVIEW_REQUIRED",
                           counterpart_source_ids="", placement_note=note)
                unmatched[section].append(row)
        for section in sections:
            for key, group in conventional.items():
                if group[0]["section"] != section:
                    continue
                ordered.extend(dict(row, display_section=row["section"],
                                    placement_status="CONVENTIONAL", counterpart_source_ids="",
                                    placement_note="") for row in group)
                ordered.extend(paired[key])
            ordered.extend(unmatched[section])
    positions = Counter()
    for row in ordered:
        positions[row["book"]] += 1
        row["booklet_position"] = positions[row["book"]]
    return ordered


def booklet_image(row, images):
    content = images[row["source_id"]]
    return render_watermark(content) if row["organic"] else content


def build_documents(root, output, rows, images, assignments, digest):
    import docx
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.shared import Inches, Pt

    presentation = booklet_order(rows, assignments)
    for book, filename in BOOKS.items():
        selected = [row for row in presentation if row["book"] == book]
        document = docx.Document()
        section = document.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = Inches(11), Inches(8.5)
        section.top_margin = section.bottom_margin = Inches(0.35)
        section.left_margin = section.right_margin = Inches(0.4)
        style = document.styles["Normal"]
        style.font.name, style.font.size = "DejaVu Sans", Pt(10)
        style.paragraph_format.space_after = Pt(2)
        document.core_properties.identifier = "picklist-sha256:" + digest
        document.add_heading(book + " PLU Reference", 0)
        document.add_paragraph("Generated from owner-maintained PickList.xml. Exact source values retained.")
        document.add_paragraph("Source SHA-256: " + digest)
        if not selected:
            document.add_paragraph("No visible products in this booklet.")
        for start in range(0, len(selected), 6):
            document.add_page_break()
            table = document.add_table(rows=3, cols=2)
            table.style = "Table Grid"
            for table_row in table.rows:
                table_row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            for offset, row in enumerate(selected[start:start + 6]):
                cell = table.cell(offset // 2, offset % 2)
                cell.paragraphs[0].add_run("PLU: " + row["plu"]).bold = True
                cell.add_paragraph(row["name"])
                cell.add_paragraph("Section: " + row["display_section"])
                if row["source_id"] in images:
                    content = booklet_image(row, images)
                    with Image.open(io.BytesIO(content)) as image:
                        width, height = image.size
                    scale = min(3.7 / width, 1.0 / height)
                    cell.add_paragraph().add_run().add_picture(
                        io.BytesIO(content), width=Inches(width * scale),
                        height=Inches(height * scale))
                    cell.add_paragraph("Reviewed photographic reference" +
                                       ("; organic label is not certification." if row["organic"] else ""))
                else:
                    cell.add_paragraph("CODE-ONLY REFERENCE; no photograph.")
        photo_rows = [row for row in selected if row["source_id"] in images]
        if photo_rows:
            document.add_page_break()
            document.add_heading("Photograph credits and modifications", 1)
            for row in photo_rows:
                provenance = assignments[row["source_id"]]["provenance"]
                document.add_paragraph(row["name"] + " (code " + row["plu"] + ")", style="Heading 2")
                document.add_paragraph(provenance["attribution"])
                document.add_paragraph("Source: " + provenance["source_page_url"])
                document.add_paragraph(provenance["license"] + ": " + provenance["license_url"])
                changes = provenance["changes"] + ("; pink organic badge added" if row["organic"] else "")
                document.add_paragraph("Modifications: " + changes)
        document.save(output / (filename + ".docx"))
    credits = []
    for row in rows:
        if row["source_id"] in images:
            provenance = assignments[row["source_id"]]["provenance"]
            credit = dict(source_id=row["source_id"], plu=row["plu"], product=row["name"], **provenance)
            if row["organic"]:
                credit["changes"] += "; pink organic badge added"
            credits.append(credit)
    csv_output(output / "PHOTO_ATTRIBUTIONS.csv", credits,
               ["source_id", "plu", "product", "creator", "license", "license_url",
                "source_page_url", "original_image_url", "attribution", "changes", "rights_evidence"])


def excel_row(sheet, number, values):
    for column, value in enumerate(values, 1):
        if len(value) > 32767:
            raise ValueError(f"{sheet.title} row {number}: text exceeds Excel's cell limit")
        cell = sheet.cell(number, column, value)
        cell.data_type = "s"
        cell.number_format = "@"


def build_workbooks(output, rows, images, assignments, digest):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as ExcelImage
    from openpyxl.styles import Alignment, Font, PatternFill

    presentation = booklet_order(rows, assignments)
    for book, filename in BOOKS.items():
        selected = [row for row in presentation if row["book"] == book]
        workbook = Workbook()
        workbook.properties.title = book + " PLU Reference"
        workbook.properties.identifier = "picklist-sha256:" + digest
        sheet = workbook.active
        sheet.title = "Booklet"
        excel_row(sheet, 1, [book + " PLU Reference"])
        sheet.merge_cells("A1:F1")
        excel_row(sheet, 2, ["Source SHA-256", digest])
        sheet.merge_cells("B2:F2")
        excel_row(sheet, 4, ["PLU", "Product", "Section", "Organic", "Photograph", "Notes"])
        for number, row in enumerate(selected, 5):
            has_image = row["source_id"] in images
            note = "CODE-ONLY REFERENCE; no photograph."
            if has_image:
                note = "Reviewed photographic reference"
                if row["organic"]:
                    note += "; organic label is not certification."
            if row["placement_note"]:
                note = "; ".join(filter(None, [note, row["placement_note"]]))
            excel_row(sheet, number, [row["plu"], row["name"], row["display_section"],
                                      "YES" if row["organic"] else "NO", "", note])
            sheet.row_dimensions[number].height = 90 if has_image else 36
            if has_image:
                picture = ExcelImage(io.BytesIO(booklet_image(row, images)))
                scale = min(224 / picture.width, 112 / picture.height)
                picture.width *= scale
                picture.height *= scale
                sheet.add_image(picture, f"E{number}")
        sheet.freeze_panes = "B5"
        sheet.auto_filter.ref = f"A4:F{max(4, sheet.max_row)}"
        sheet.print_title_rows = "1:4"
        sheet.print_area = f"A1:F{sheet.max_row}"
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_LETTER
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        credits = workbook.create_sheet("Photo credits")
        excel_row(credits, 1, [
            "PLU", "Product", "Creator", "Licence", "Licence URL", "Source page URL",
            "Original image URL", "Attribution", "Changes", "Rights evidence", "Source ID",
        ])
        for row in selected:
            if row["source_id"] not in images:
                continue
            provenance = assignments[row["source_id"]]["provenance"]
            changes = provenance["changes"] + ("; pink organic badge added" if row["organic"] else "")
            excel_row(credits, credits.max_row + 1, [
                row["plu"], row["name"], provenance["creator"], provenance["license"],
                provenance["license_url"], provenance["source_page_url"],
                provenance["original_image_url"], provenance["attribution"], changes,
                provenance["rights_evidence"], row["source_id"],
            ])
        credits.freeze_panes = "C2"
        credits.auto_filter.ref = credits.dimensions
        for worksheet, header, widths in (
                (sheet, 4, [18, 38, 24, 12, 34, 48]),
                (credits, 1, [18, 38, 28, 18, 42, 48, 48, 48, 40, 48, 68])):
            for cells in worksheet.iter_rows(min_row=header):
                for cell in cells:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            for cell in worksheet[header]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="305040")
            for column, width in enumerate(widths, 1):
                worksheet.column_dimensions[worksheet.cell(header, column).column_letter].width = width
        workbook.save(output / (filename + ".xlsx"))


def verify_workbooks(output, rows, assignments, digest):
    from openpyxl import load_workbook

    presentation = booklet_order(rows, assignments)
    for book, filename in BOOKS.items():
        workbook = load_workbook(output / (filename + ".xlsx"), read_only=True)
        try:
            if workbook.properties.identifier != "picklist-sha256:" + digest:
                raise ValueError(f"{book}: Excel source checksum differs from current PickList")
            sheet = workbook["Booklet"]
            selected = [row for row in presentation if row["book"] == book]
            actual = [(a.value, b.value, c.value, d.value)
                      for a, b, c, d in sheet.iter_rows(min_row=5, max_col=4)]
            expected = [(row["plu"], row["name"] or None, row["display_section"] or None,
                         "YES" if row["organic"] else "NO") for row in selected]
            if actual != expected:
                raise ValueError(f"{book}: Excel entries differ from XML-derived booklet order")
            if any(cell.data_type == "f" for worksheet in workbook for cells in worksheet
                   for cell in cells):
                raise ValueError(f"{book}: Excel must contain literal text, not formulas")
        finally:
            workbook.close()


def verify_pdfs(output, rows, assignments):
    from pypdf import PdfReader

    presentation = booklet_order(rows, assignments)
    for book, filename in BOOKS.items():
        pdf = PdfReader(output / (filename + ".pdf"))
        expected = [row["plu"] for row in presentation if row["book"] == book]
        text = "\n".join(page.extract_text() for page in pdf.pages)
        actual = re.findall(r"PLU:\s*(\S+)", text)
        if actual != expected:
            raise ValueError(f"{book}: PDF code sequence differs from XML-derived booklet order")
        if any(abs(float(page.mediabox.width) - 792) > 1 or
               abs(float(page.mediabox.height) - 612) > 1 for page in pdf.pages):
            raise ValueError(f"{book}: expected landscape US Letter pages")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True, help="Empty staging directory")
    parser.add_argument("--catalog-only", action="store_true", help="Write reconciliation; never publish")
    parser.add_argument("--pdf", action="store_true", help="Export and verify PDFs after all gates pass")
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        if any(args.output.iterdir()):
            raise ValueError("output must be empty; existing booklets will never be overwritten")
        rows, images, assignments, summary = reconcile(args.root, args.output)
        print(json.dumps(summary, indent=2))
        if hashlib.sha256((args.root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != summary["source_sha256"]:
            raise ValueError("source changed during reconciliation; discard output and retry")
        if args.catalog_only:
            return
        if summary["status"] != "READY_TO_BUILD":
            parser.exit(1, "BLOCKED: see PICKLIST_SYNC.csv; no booklets were published.\n")
        build_documents(args.root, args.output, rows, images, assignments, summary["source_sha256"])
        build_workbooks(args.output, rows, images, assignments, summary["source_sha256"])
        verify_workbooks(args.output, rows, assignments, summary["source_sha256"])
        if args.pdf:
            subprocess.run([
                "soffice", "-env:UserInstallation=" + (args.output.resolve() / "lo-profile").as_uri(),
                "--headless", "--convert-to",
                'pdf:writer_pdf_Export:{"UseLosslessCompression":{"type":"boolean","value":"true"},'
                '"ReduceImageResolution":{"type":"boolean","value":"false"}}',
                "--outdir", str(args.output), *map(str, sorted(args.output.glob("*.docx"))),
            ], check=True, timeout=300)
            verify_pdfs(args.output, rows, assignments)
        if hashlib.sha256((args.root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != summary["source_sha256"]:
            raise ValueError("source changed during build; discard staging output and retry")
        (args.output / "BUILD_VERIFIED.json").write_text(json.dumps(dict(
            source_sha256=summary["source_sha256"], records=len(rows),
            pdfs_verified=args.pdf, workbooks_verified=True, status="AWAITING_OWNER_RELEASE_REVIEW",
        ), indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
