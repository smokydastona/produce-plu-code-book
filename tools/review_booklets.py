"""Render cashier-only review booklets without bypassing production publication gates."""
import argparse
import csv
import io
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from PIL import Image

from picklist_catalog import read_assignments
from review_image_references import load_references
from sync_picklist import BOOKS, booklet_order, csv_output
from working_list import read_working_list, rebuild_working_list

ORIGINAL_BINDER_SHA256 = "6b0aeaa153233c5f4917811a3f7a5b2212f7a946a0abede372a31db556ab0f63"


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


def build_working_list_review(root, output, pdf=False):
    root, output = Path(root), Path(output)
    binder_path = root / "sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx"
    binder_available = binder_path.is_file()
    if binder_available and hashlib.sha256(binder_path.read_bytes()).hexdigest() != ORIGINAL_BINDER_SHA256:
        raise ValueError("Original binder checksum differs; do not reconstruct or replace it")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty; existing production and review files are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    reconciliation = output / "reconciliation"
    rebuild_working_list(root, reconciliation)
    items, digest = read_working_list(root)
    assignments = read_assignments(root / "data/picklist_assignments.json")
    from build_till_binders import map_images, produce_catalog, visual_records

    rows, _ = produce_catalog(items, assignments)
    images, photo_report = map_images(root, rows, assignments, visual_records(root))
    _, reference_audit = load_references(root, rows)
    active_counts = Counter(item["plu"] for item in items if item["included"])
    non_produce = [
        dict(item, book="Non-produce",
             section=assignments[item["classification_source_id"]]["section"],
             organic=False, duplicate_count=active_counts[item["plu"]])
        for item in items if item["included"] and
        assignments.get(item["classification_source_id"], {}).get("book") == "Non-produce"
    ]
    booklet_stage = output / "_booklets"
    results = build_review_booklets(
        booklet_stage, rows + non_produce, images, assignments, digest, pdf=pdf)
    csv_output(output / "PHOTO_MAPPING.csv", photo_report, [
        "source_id", "source_identity_ids", "plu", "product", "image_status", "embedded",
        "image_source", "source_document", "source_member", "original_sha256",
        "embedded_sha256", "width", "height", "visual_verdict", "visual_review_note",
        "rights_status", "photograph_status", "organic_badge", "reused_by_entries", "details",
    ])
    csv_output(output / "MISSING_IMAGES.csv", [
        row for row in photo_report if not row["embedded"]
    ], ["source_id", "source_identity_ids", "plu", "product", "image_status",
        "visual_review_note", "details"])
    csv_output(output / "AI_REFERENCE_REVIEW.csv", reference_audit, [
        "source_id", "source_identity_ids", "plu", "product", "decision", "status", "source_document",
        "source_sha256", "source_member", "crop_box", "crop_sha256", "width", "height",
        "image_source", "rights_status", "details",
    ])
    csv_output(output / "PLACEMENT_REVIEW.csv", [
        row for row in rows if row["placement_status"] == "PLACEMENT_REVIEW_REQUIRED" or
        row["classification_status"] != "EXISTING_CLASSIFICATION"
    ], ["source_id", "plu", "name", "display_section", "classification_status",
        "placement_status", "counterpart_source_ids", "placement_note"])
    for name in ("DUPLICATE_PLU_CLASSIFICATIONS.csv",
                 "DUPLICATE_PLU_CLASSIFICATION_REVIEW.md"):
        shutil.copy2(root / "current/review-booklets" / name, output / name)
    for path in booklet_stage.iterdir():
        if path.is_file() and path.name not in {
                "AI_REFERENCE_REVIEW.csv", "MISSING_IMAGES.csv",
                "PHOTO_MAPPING.csv", "PLACEMENT_REVIEW.csv"}:
            shutil.copy2(path, output / path.name)
    shutil.rmtree(booklet_stage)
    report = json.loads((reconciliation / "WORKING_LIST_RECONCILIATION.json").read_text(
        encoding="utf-8"))
    report.update(
        status="REVIEW_ONLY_NOT_RELEASED",
        production_publication="BLOCKED",
        active_working_records=sum(item["included"] for item in items),
        produce_records=len(rows),
        non_produce_records=len(non_produce),
        image_references_embedded=len(images),
        image_review_required=sum(row["identity_changed"] for row in rows),
        missing_or_unapproved_images=sum(not row["embedded"] for row in photo_report),
        image_status_counts=dict(sorted(Counter(row["image_status"] for row in photo_report).items())),
        image_reference_audit_status_counts=dict(sorted(
            Counter(row["status"] for row in reference_audit).items())),
        supplier_reference_mappings=sum(
            row.get("decision") == "SUPPLIER_REFERENCE" for row in reference_audit),
        supplier_mappings_requiring_fresh_review=sum(
            row.get("status") == "WORKING_IDENTITY_REVIEW_REQUIRED" and
            row.get("decision") == "SUPPLIER_REFERENCE" for row in reference_audit),
        review_booklets=results,
        limitation="This command generates standalone reviews only; production booklets remain untouched.",
        complete_binder_regeneration=dict(
            status="ORIGINAL_AVAILABLE_NOT_RUN" if binder_available else "BLOCKED_MISSING_ORIGINAL",
            expected_path=str(binder_path.relative_to(root)),
            expected_sha256=ORIGINAL_BINDER_SHA256,
        ),
    )
    pdf_layouts = ", ".join(
        f"{book}: {result['records']} entries, {result['pdf']['pages']} pages"
        for book, result in results.items() if isinstance(result["pdf"], dict))
    pdf_summary = ("Verified PDF layouts: " + pdf_layouts + ".\n"
                   if pdf_layouts else "PDF layout verification was not run.\n")
    (output / "BUILD_NOTES.txt").write_text(
        "WORKINGLIST CASHIER REVIEW EDITIONS - NOT A PRODUCTION RELEASE\n\n"
        f"PickList SHA-256: {digest}\n"
        f"Source records: {report['source_records']}; WorkingList records: "
        f"{report['working_records']}; cashier entries: {report['produce_records']} Produce "
        f"and {report['non_produce_records']} non-produce.\n"
        f"Embedded unchanged-identity image references: {report['image_references_embedded']}.\n"
        f"Changed identities held blank for fresh image review: {report['image_review_required']}.\n"
        f"Supplier references: {report['supplier_reference_mappings']} exact mappings; "
        f"{report['supplier_mappings_requiring_fresh_review']} require fresh identity review.\n"
        "PLU 94093 remains unstandardized pending supplier confirmation. PLU 4727 displays "
        "Yellow Potatoes; the Yukon Gold alias remains unconfirmed and is not included.\n"
        "All original PickList records, including excluded associations, are retained in the "
        "reconciliation audit. Cashier entries show only PLU, product name and optional image.\n"
        + pdf_summary
        + "PDF checks verify exact PLUs and names, image counts and landscape US Letter geometry; "
        "image references, rights and product suitability still require review.\n\n"
        "This standalone command does not regenerate complete till binders.\n"
        f"Original workbook: {'available and checksum-verified' if binder_available else 'missing'}.\n"
        f"  {report['complete_binder_regeneration']['expected_path']}\n"
        f"Expected SHA-256: {report['complete_binder_regeneration']['expected_sha256']}\n"
        "Do not reconstruct it from prior outputs. Existing binder copies were not overwritten. "
        "Previously published production booklets and approval registries remain unchanged.\n",
        encoding="utf-8")
    report["file_sha256"] = {
        str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.rglob("*")) if path.is_file()
    }
    (output / "WORKING_LIST_REVIEW.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    checksum_paths = [
        path for path in sorted(output.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    checksum_paths.extend([
        root / "sources/plu/PickList.xml",
        root / "sources/plu/WorkingList.xml",
        root / "data/working_list_decisions.json",
    ])
    if binder_available:
        checksum_paths.append(binder_path)
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"{path.relative_to(output) if path.is_relative_to(output) else
           path.relative_to(root) if path.is_relative_to(root) else path.name}\n"
        for path in checksum_paths), encoding="utf-8")
    if hashlib.sha256((root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != digest:
        raise ValueError("PickList changed during review generation; discard output and retry")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True, help="Empty review output directory")
    parser.add_argument("--pdf", action="store_true", help="Export and verify landscape US Letter PDFs")
    args = parser.parse_args()
    try:
        report = build_working_list_review(args.root, args.output, args.pdf)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps({key: report[key] for key in (
        "source_sha256", "source_records", "working_records", "produce_records",
        "image_references_embedded", "missing_or_unapproved_images",
        "production_publication")}, indent=2))


if __name__ == "__main__":
    main()
