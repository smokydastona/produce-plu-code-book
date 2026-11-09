"""Render cashier-only review booklets without bypassing production publication gates."""
import io
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image

from sync_picklist import BOOKS, booklet_order, csv_output


def build_document(path, book, rows, images, digest):
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11), Inches(8.5)
    section.top_margin = section.bottom_margin = Inches(.4)
    section.left_margin = section.right_margin = Inches(.4)
    style = document.styles["Normal"]
    style.font.name, style.font.size = "DejaVu Sans", Pt(10)
    style.paragraph_format.space_after = Pt(2)
    section.header.paragraphs[0].text = book + " PLU Quick Reference"
    section.footer.paragraphs[0].text = "Red PLU = shared code: confirm the product before entry"
    document.core_properties.identifier = "picklist-sha256:" + digest
    document.core_properties.subject = "REVIEW ONLY - not a production release"
    for start in range(0, len(rows), 6):
        if start:
            document.add_page_break()
        table = document.add_table(rows=3, cols=2)
        table.style = "Table Grid"
        for table_row in table.rows:
            table_row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for offset, row in enumerate(rows[start:start + 6]):
            cell = table.cell(offset // 2, offset % 2)
            code = cell.paragraphs[0].add_run("PLU: " + row["plu"])
            code.bold = True
            if row["duplicate_count"] > 1:
                code.font.color.rgb = RGBColor.from_string("9C0006")
            cell.add_paragraph(row["name"])
            if row["source_id"] in images:
                content = images[row["source_id"]]
                with Image.open(io.BytesIO(content)) as image:
                    width, height = image.size
                scale = min(3.8 / width, 1.15 / height)
                cell.add_paragraph().add_run().add_picture(
                    io.BytesIO(content), width=Inches(width * scale),
                    height=Inches(height * scale))
    document.save(path)


def validate_documents(path, workbook_path, rows, images, coordinates, digest):
    document = Document(path)
    cells = [cell for table in document.tables for table_row in table.rows for cell in table_row.cells]
    populated = [cell for cell in cells if cell.text.strip()]
    if len(populated) != len(rows):
        raise ValueError(f"{path.name}: wrong record count")
    for cell, row in zip(populated, rows):
        text = [paragraph.text for paragraph in cell.paragraphs if paragraph.text]
        if text != ["PLU: " + row["plu"], row["name"]]:
            raise ValueError(f"{path.name}: changed source text or unexpected cashier labels")
        blips = list(cell._tc.iter(qn("a:blip")))
        expected = images.get(row["source_id"])
        if len(blips) != int(expected is not None):
            raise ValueError(f"{path.name}: wrong per-product image count")
        if expected is not None:
            embedded = document.part.related_parts[blips[0].get(qn("r:embed"))].blob
            if embedded != expected:
                raise ValueError(f"{path.name}: image differs from reviewed mapping")
    if document.core_properties.identifier != "picklist-sha256:" + digest:
        raise ValueError(f"{path.name}: source digest missing")
    workbook = load_workbook(workbook_path)
    try:
        sheet = workbook["Produce"]
        if workbook.properties.identifier != "picklist-sha256:" + digest:
            raise ValueError(f"{workbook_path.name}: source digest missing")
        if sheet.page_setup.orientation != "landscape" or sheet.page_setup.fitToWidth != 1:
            raise ValueError(f"{workbook_path.name}: print settings changed")
        expected_images = {}
        for entry in coordinates:
            code, name = sheet[entry["code_cell"]], sheet[entry["description_cell"]]
            if (code.value, code.data_type, code.number_format) != (entry["plu"], "s", "@"):
                raise ValueError(f"{workbook_path.name}: PLU is not exact text")
            if name.value != entry["product"] or name.data_type != "s":
                raise ValueError(f"{workbook_path.name}: source description changed")
            if sheet[entry["image_cell"]].value is not None:
                raise ValueError(f"{workbook_path.name}: cashier-facing image label")
            if entry["source_id"] in images:
                expected_images[entry["image_cell"]] = images[entry["source_id"]]
        if len(expected_images) != len(sheet._images):
            raise ValueError(f"{workbook_path.name}: image count mismatch")
        for picture in sheet._images:
            anchor = picture.anchor._from
            coordinate = get_column_letter(anchor.col + 1) + str(anchor.row + 1)
            if expected_images.pop(coordinate, None) != picture._data():
                raise ValueError(f"{workbook_path.name}: changed image or anchor")
        if expected_images:
            raise ValueError(f"{workbook_path.name}: missing images")
    finally:
        workbook.close()
    return dict(records=len(rows), images=sum(row["source_id"] in images for row in rows),
                exact_docx_and_excel_text=True, embedded_image_bytes_and_anchors=True,
                cashier_image_labels_absent=True)


def validate_pdf(path, rows, images):
    from pypdf import PdfReader

    pdf = PdfReader(path)
    actual, drawn = [], 0
    if len(pdf.pages) != (len(rows) + 5) // 6:
        raise ValueError(f"{path.name}: unexpected overflow/blank pages")
    for index, page in enumerate(pdf.pages):
        if abs(float(page.mediabox.width) - 792) > 1 or abs(float(page.mediabox.height) - 612) > 1:
            raise ValueError(f"{path.name}: not landscape US Letter")
        text = page.extract_text()
        selected = rows[index * 6:index * 6 + 6]
        actual.extend(re.findall(r"PLU:\s*(\S+)", text))
        normalized = " ".join(text.split())
        if any(" ".join(row["name"].split()) not in normalized for row in selected):
            raise ValueError(f"{path.name}: missing or clipped printed description")
        resources = page["/Resources"].get("/XObject", {})
        count = sum(resources[operands[0]].get_object().get("/Subtype") == "/Image"
                    for operands, operator in page.get_contents().operations if operator == b"Do")
        if count != sum(row["source_id"] in images for row in selected):
            raise ValueError(f"{path.name}: printed image count mismatch on page {index + 1}")
        drawn += count
    if actual != [row["plu"] for row in rows]:
        raise ValueError(f"{path.name}: printed PLUs differ from exact XML order")
    return dict(pages=len(pdf.pages), drawn_images=drawn, exact_printed_codes=True,
                every_description_on_planned_page=True, landscape_us_letter=True)


def build_review_booklets(output, rows, images, assignments, digest, pdf=False):
    from build_till_binders import quick_sheet

    output.mkdir()
    presentation = booklet_order(rows, assignments)
    results = {}
    for book, stem in BOOKS.items():
        stem = stem.replace("_PRODUCTION", "").replace("_CASHIER", "") + "_REVIEW"
        selected = [row for row in presentation if row["book"] == book]
        if not selected:
            raise ValueError(f"review booklet has no {book} records")
        document_path = output / (stem + ".docx")
        workbook_path = output / (stem + ".xlsx")
        build_document(document_path, book, selected, images, digest)
        content, coordinates, pages = quick_sheet(selected, images, True, title=book.upper())
        workbook = load_workbook(io.BytesIO(content))
        workbook.properties.identifier = "picklist-sha256:" + digest
        workbook.properties.subject = "REVIEW ONLY - not a production release"
        workbook.save(workbook_path)
        workbook.close()
        results[book] = validate_documents(
            document_path, workbook_path, selected, images, coordinates, digest)
        results[book].update(stem=stem, excel_planned_pages=pages, pdf="NOT_RUN")
        csv_output(output / (stem + "_LAYOUT.csv"), coordinates, [
            "source_id", "plu", "product", "code_cell", "description_cell", "image_cell",
            "page", "duplicate_count",
        ])
    if pdf:
        with tempfile.TemporaryDirectory(prefix="review-booklet-") as directory:
            process = subprocess.run([
                "soffice", "-env:UserInstallation=" + Path(directory).as_uri(),
                "--headless", "--convert-to",
                'pdf:writer_pdf_Export:{"UseLosslessCompression":{"type":"boolean","value":"true"},'
                '"ReduceImageResolution":{"type":"boolean","value":"false"}}',
                "--outdir", str(output.resolve()),
                *map(str, sorted(output.resolve().glob("*.docx"))),
            ], check=True, capture_output=True, text=True, timeout=300)
            (output / "PRINT_ENGINE_LOG.txt").write_text(
                process.stdout + process.stderr, encoding="utf-8")
        for book, result in results.items():
            result["pdf"] = validate_pdf(output / (result["stem"] + ".pdf"),
                                        [row for row in presentation if row["book"] == book], images)
    (output / "REVIEW_VALIDATION.json").write_text(json.dumps(dict(
        status="REVIEW_ONLY_NOT_RELEASED", production_publication="BLOCKED",
        source_sha256=digest, records=len(rows), images=len(images), booklets=results,
        file_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(output.iterdir()) if path.suffix in {".docx", ".pdf", ".xlsx"}},
        limitations=[
            "AI visual references are not photographs or rights approvals.",
            "Source classifications, organic pairings, image suitability, resolution and reuse still need review.",
            "Automated text, image and page checks do not replace store-printer and visual approval.",
            "Previously published production booklets and all approval registries remain unchanged.",
        ],
    ), indent=2) + "\n", encoding="utf-8")
    return results
