import csv
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Font
from PIL import Image

from build_till_binders import (FILENAMES, MAX_GITHUB_FILE_SIZE, VISUALS, comparisons, generate, layout_rows,
                               docx_compatible_image,
                               map_images, produce_catalog, quick_sheet, replace_produce,
                               sha, validate_package, visual_records, workbook_photo_copy)
from picklist_catalog import read_picklist, read_assignments
from review_image_references import load_references
from review_booklets import build_review_booklets, build_working_list_review
from organic_watermarks import render_watermark
from build_deli_sheet import convert


class TillBinderChecks(unittest.TestCase):
    def test_supplier_jpeg_is_losslessly_made_docx_compatible(self):
        source = Path(__file__).resolve().parents[1] / "data/review-references/buck-brand/page-02-image-011.jpeg"
        original = source.read_bytes()
        converted = docx_compatible_image(original)
        self.assertNotEqual(converted, original)
        document = Document()
        document.add_paragraph().add_run().add_picture(io.BytesIO(converted))
        with Image.open(io.BytesIO(original)) as before, Image.open(io.BytesIO(converted)) as after:
            self.assertEqual(before.size, after.size)
            self.assertEqual(before.convert("RGB").tobytes(), after.convert("RGB").tobytes())
        self.assertEqual(source.read_bytes(), original)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for folder in ("sources/plu", "sources/visual", "data"):
            (self.root / folder).mkdir(parents=True)
        self.binder = self.root / "Original.xlsx"
        image = io.BytesIO()
        Image.new("RGB", (600, 500), "green").save(image, format="PNG")
        self.content = image.getvalue()
        self.image = self.root / "data/reference.png"
        self.image.write_bytes(self.content)
        original = Workbook()
        first = original.active
        first.title = "Operational"
        first["A1"] = "Do not change"
        first["A1"].font = Font(bold=True, color="FF0055")
        first.merge_cells("A1:C1")
        first["A2"], first["A3"] = 2, 3
        first["B2"] = "=SUM(A2:A3)"
        first["B2"].comment = Comment("Keep this comment", "Fixture")
        first.column_dimensions["A"].width = 28
        first.row_dimensions[2].height = 40
        first.freeze_panes = "B2"
        first.print_area = "A1:D10"
        first.print_title_rows = "1:1"
        first.add_image(ExcelImage(io.BytesIO(self.content)), "C3")
        chart = BarChart()
        chart.add_data(Reference(first, min_col=1, min_row=2, max_row=3))
        first.add_chart(chart, "E1")
        produce = original.create_sheet("Produce")
        produce["A1"], produce["B1"] = 42, "Old Gala"
        produce["D1"], produce["E1"] = "900042", "Organic Apple Gala"
        produce["H1"], produce["I1"] = "99999", "Removed"
        produce["A2"] = "CATEGORY"
        produce.merge_cells("A2:B2")
        produce["A3"], produce["B3"] = " 00042 ", "Apple Gala"
        produce["A4"], produce["B4"] = "00046", "Hidden Apple"
        produce["B5"] = "Description without code"
        produce.print_area = "A1:I6"
        deli = original.create_sheet("Deli")
        deli["A1"] = "Outdated deli"
        deli.print_area = "A1:B2"
        last = original.create_sheet("Hidden operations")
        last.sheet_state = "hidden"
        last["A1"] = "=Operational!B2"
        original.save(self.binder)
        deli_document = Document()
        deli_document.add_heading("DELI PRODUCT & PLU REFERENCE GUIDE", 0)
        for category, product, plu in (("Meals", "Updated meal", "00012"), ("Salads", "Updated salad", "00013")):
            deli_document.add_heading(category, 1)
            table = deli_document.add_table(rows=2, cols=2)
            table.cell(0, 0).text, table.cell(0, 1).text = "Product", "PLU"
            table.cell(1, 0).text, table.cell(1, 1).text = product, plu
        upload = self.root / "Uploaded_Deli.docx"
        deli_document.save(upload)
        convert(upload, self.root / "sources/binders")
        with zipfile.ZipFile(self.binder, "a") as archive:
            archive.writestr("customXml/untouched.xml", b"<custom>unchanged opaque object</custom>")
        self.write_source([
            ("900042", "Organic Apple Gala", True, False),
            ("00042", "Apple Gala", True, False),
            ("00042", "Different Apple", True, False),
            ("00044", "Questionable Fruit", True, False),
            ("00045", "AI Apple", True, False),
            ("00046", "Hidden Apple", False, False),
            ("00047", "Deleted Apple", True, True),
            ("00048", "Operational Code", True, False),
            ("00049", "Organic Melon New", True, False),
            ("00050", "=Unusual Apple", True, False),
        ])
        self.items, self.digest = read_picklist(self.root / "sources/plu/PickList.xml")
        (self.root / "data/working_list_decisions.json").write_text(json.dumps(dict(
            schema_version=1, baseline_source_sha256=self.digest,
            baseline=[dict(source_id=item["source_id"], plu=item["plu"], name=item["name"],
                           department=item["department"], occurrence=item["occurrence"],
                           visible=item["visible"], deleted=item["deleted"]) for item in self.items],
            decisions=[])))
        assignments, reviews = [], []
        fruit = Document()
        for number, item in enumerate(self.items):
            if number in (5, 6, 8):
                continue
            assignment = dict(
                source_id=item["source_id"], book="Fruit", section="Organic Fruit" if number == 0 else "Apples",
                image="data/reference.png", image_mode="PHOTO", reviewed_plu=item["plu"],
                reviewed_product=item["name"], legacy_entry_idx=str(number + 1),
                image_sha256=sha(self.content), visual_approval_status="NOT_APPROVED",
                photographic_origin="NOT_VERIFIED", rights_verification_status="NOT_VERIFIED", provenance={},
            )
            if number == 7:
                assignment.update(book="Non-produce", section="Misc", image="",
                                  image_mode="CODE_ONLY", code_only_approved=True)
            else:
                source = "AI Generated" if number == 4 else "Code Booklet"
                cell = fruit.add_table(rows=1, cols=1).cell(0, 0)
                cell.text = f"PLU: {item['plu']}"
                for text in (item["name"], "Category: Apple", "Image Source: " + source):
                    cell.add_paragraph(text)
                cell.add_paragraph().add_run().add_picture(io.BytesIO(self.content))
                reviews.append(dict(idx=str(number + 1), plu=item["plu"], name=item["name"],
                                    verdict="Approximate" if number == 3 else "Approved"))
            assignments.append(assignment)
        fruit.save(self.root / "sources/visual" / VISUALS["Fruit"])
        Document().save(self.root / "sources/visual" / VISUALS["Vegetable"])
        (self.root / "data/picklist_assignments.json").write_text(json.dumps(
            dict(schema_version=1, assignments=assignments)))
        with (self.root / "data/image_review.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["idx", "plu", "name", "verdict"])
            writer.writeheader()
            writer.writerows(reviews)
        self.output = self.root / "output"

    def write_source(self, values):
        root = ET.Element("PickList")
        items = ET.SubElement(root, "Items")
        for plu, name, visible, deleted in values:
            item = ET.SubElement(items, "Item", UPC=plu)
            ET.SubElement(item, "Department").text = "001"
            ET.SubElement(item, "IsVisible").text = str(visible)
            ET.SubElement(item, "DeleteThisItem").text = str(deleted)
            language = ET.SubElement(ET.SubElement(item, "Languages"), "Language", LCID="0409")
            ET.SubElement(language, "Description").text = name
        (self.root / "sources/plu/PickList.xml").write_bytes(ET.tostring(root, encoding="utf-16"))

    def test_full_workbooks_preserve_opaque_parts_formulas_objects_and_original(self):
        before = self.binder.read_bytes()
        source_before = (self.root / "sources/plu/PickList.xml").read_bytes()
        summary = generate(self.root, self.binder, self.output)
        self.assertEqual(summary["produce_records_included"], 7)
        self.assertEqual(summary["total_source_records"], 10)
        self.assertEqual(summary["hidden_or_deleted_records"], 2)
        self.assertEqual(summary["known_non_produce_excluded"], 1)
        self.assertEqual(summary["duplicate_produce_codes"], 1)
        self.assertEqual(summary["embedded_references"], 5)
        self.assertEqual(summary["ai_illustrations_omitted"], 0)
        self.assertEqual(summary["ai_illustrations_embedded"], 1)
        self.assertEqual(summary["production_publication"], "BLOCKED")
        for edition, filename in FILENAMES.items():
            path = self.output / filename
            workbook = load_workbook(path)
            self.addCleanup(workbook.close)
            self.assertEqual(workbook.sheetnames, ["Operational", "Produce", "Deli", "Hidden operations"])
            self.assertEqual(workbook["Deli"]["B5"].value, "00012")
            self.assertEqual(workbook["Deli"]["E5"].value, "00013")
            self.assertEqual(summary["validations"][edition]["deli_records_verified"], 2)
            self.assertEqual(workbook["Operational"]["B2"].value, "=SUM(A2:A3)")
            self.assertEqual(workbook["Operational"]["B2"].comment.text, "Keep this comment")
            self.assertEqual(str(workbook["Operational"].merged_cells), "A1:C1")
            self.assertEqual(len(workbook["Operational"]._images), 1)
            self.assertEqual(len(workbook["Operational"]._charts), 1)
            self.assertEqual(workbook["Hidden operations"].sheet_state, "hidden")
            self.assertTrue(summary["validations"][edition]["unrelated_package_parts_byte_identical"])
            if edition == "photos":
                self.assertLess(summary["validations"][edition]["file_size_bytes"], MAX_GITHUB_FILE_SIZE)
            self.assertEqual(len(workbook["Produce"]._images), 5 if edition == "photos" else 0)
            if edition == "photos":
                formats = set()
                for picture in workbook["Produce"]._images:
                    with Image.open(io.BytesIO(picture._data())) as image:
                        formats.add(image.format)
                self.assertEqual(formats, {"JPEG"})
            self.assertTrue(all(cell.data_type != "f" for row in workbook["Produce"] for cell in row))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read("customXml/untouched.xml"), b"<custom>unchanged opaque object</custom>")
        self.assertEqual(self.binder.read_bytes(), before)
        self.assertEqual((self.root / "sources/plu/PickList.xml").read_bytes(), source_before)
        self.assertEqual(self.image.read_bytes(), self.content)
        self.assertTrue((self.output / "PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt").is_file())
        with self.assertRaisesRegex(ValueError, "empty"):
            generate(self.root, self.binder, self.output)

    def test_workbook_photo_copies_keep_transparency_and_do_not_change_source_bytes(self):
        opaque = io.BytesIO()
        Image.new("RGB", (40, 30), (40, 120, 200)).save(opaque, format="PNG")
        opaque_bytes = opaque.getvalue()
        opaque_copy = workbook_photo_copy(opaque_bytes)
        with Image.open(io.BytesIO(opaque_copy)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (40, 30))

        enlarged = io.BytesIO()
        Image.new("RGB", (1200, 600), (40, 120, 200)).save(enlarged, format="PNG")
        enlarged_bytes = enlarged.getvalue()
        resized_copy = workbook_photo_copy(enlarged_bytes)
        with Image.open(io.BytesIO(resized_copy)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (192, 96))
        self.assertEqual(enlarged.getvalue(), enlarged_bytes)

        transparent = io.BytesIO()
        Image.new("RGBA", (800, 400), (40, 120, 200, 0)).save(transparent, format="PNG")
        transparent_bytes = transparent.getvalue()
        transparent_copy = workbook_photo_copy(transparent_bytes)
        with Image.open(io.BytesIO(transparent_copy)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (192, 96))
            self.assertEqual(image.getchannel("A").getextrema(), (0, 0))
        self.assertEqual(opaque.getvalue(), opaque_bytes)
        self.assertEqual(transparent.getvalue(), transparent_bytes)

    def test_layout_has_only_exact_product_text_codes_categories_and_no_image_labels(self):
        generate(self.root, self.binder, self.output)
        with (self.output / "PRODUCE_LAYOUT.csv").open(encoding="utf-8-sig", newline="") as file:
            layout = list(csv.DictReader(file))
        workbook = load_workbook(self.output / FILENAMES["photos"])
        self.addCleanup(workbook.close)
        sheet = workbook["Produce"]
        for record in layout:
            code, name = sheet[record["code_cell"]], sheet[record["description_cell"]]
            self.assertEqual(code.value, record["plu"])
            self.assertEqual(code.data_type, "s")
            self.assertEqual(code.number_format, "@")
            self.assertEqual(name.value, record["product"])
            self.assertEqual(name.data_type, "s")
            self.assertIsNone(sheet[record["image_cell"]].value)
            if record["plu"] == "00042":
                self.assertEqual(code.fill.fgColor.rgb, "00FFC7CE")
        texts = [str(cell.value) for row in sheet for cell in row if cell.value is not None]
        self.assertNotIn("AI", texts)
        self.assertNotIn("REVIEW", texts)
        self.assertNotIn("CHECK", texts)
        self.assertNotIn("REF", texts)
        self.assertFalse(any("Source SHA" in text or "rights" in text.lower() for text in texts))
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(sheet.page_setup.fitToWidth, 1)
        self.assertEqual(sheet.page_setup.fitToHeight, 0)

    def test_binder_uses_working_list_and_requires_fresh_image_for_merged_identity(self):
        first, second = self.items[1], self.items[2]
        registry_path = self.root / "data/working_list_decisions.json"
        registry = json.loads(registry_path.read_text())
        registry["decisions"] = [dict(
            plu=first["plu"], canonical_name="Apple Gala", mode="MERGE",
            source_ids=[first["source_id"], second["source_id"]],
            selected_source_ids=[first["source_id"], second["source_id"]],
            condition="Owner-approved duplicate merge")]
        registry_path.write_text(json.dumps(registry))
        source_before, binder_before = (
            (self.root / "sources/plu/PickList.xml").read_bytes(), self.binder.read_bytes())
        summary = generate(self.root, self.binder, self.output)
        self.assertEqual(summary["produce_records_included"], 6)
        self.assertEqual((self.root / "sources/plu/PickList.xml").read_bytes(), source_before)
        self.assertEqual(self.binder.read_bytes(), binder_before)
        with (self.output / "PRODUCE_LAYOUT.csv").open(
                encoding="utf-8-sig", newline="") as file:
            layout = list(csv.DictReader(file))
        matching = [row for row in layout if row["plu"] == "00042"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["product"], "Apple Gala")
        with (self.output / "PHOTO_MAPPING.csv").open(
                encoding="utf-8-sig", newline="") as file:
            photos = list(csv.DictReader(file))
        image = next(row for row in photos if row["product"] == "Apple Gala")
        self.assertEqual(image["image_status"], "MISSING")
        self.assertFalse(image["embedded"] == "True")
        self.assertIn("No prior image association was reused", image["details"])

    def test_mapping_requires_exact_identity_legacy_review_and_source_checksum(self):
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        visuals = visual_records(self.root)
        images, report = map_images(self.root, rows, assignments, visuals)
        statuses = {row["plu"]: row["image_status"] for row in report}
        self.assertEqual(statuses["00045"], "AI_ILLUSTRATION_REFERENCE_REVIEW")
        self.assertEqual(statuses["00044"], "VISUAL_REVIEW_REQUIRED")
        self.assertEqual(statuses["00049"], "MISSING")
        ai = next(row for row in rows if row["plu"] == "00045")
        self.assertIn(ai["source_id"], images)
        normal = next(row for row in rows if row["plu"] == "00050")
        assignments[normal["source_id"]]["image_sha256"] = "changed"
        _, report = map_images(self.root, rows, assignments, visuals)
        self.assertEqual(next(row for row in report if row["plu"] == "00050")["image_status"],
                         "SOURCE_CHECKSUM_CHANGED")

    def test_explicit_working_list_approval_is_embedded_only_for_its_exact_identity(self):
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        row = next(item for item in rows if item["plu"] == "00042")
        assignment = assignments[row["source_id"]]
        assignment.update(
            image="data/reference.png", image_sha256=sha(self.content),
            reviewed_plu=row["plu"], reviewed_product=row["name"],
            visual_approval_status="APPROVED", photographic_origin="VERIFIED_PHOTO",
            rights_verification_status="VERIFIED",
            provenance=dict(
                creator="Test photographer", license="CC0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                source_page_url="https://example.org/apple",
                original_image_url="https://example.org/apple.png",
                attribution="Test photographer / CC0", changes="Original image unchanged",
                rights_evidence="Test fixture rights evidence",
            ),
        )
        images, report = map_images(self.root, rows, assignments, visual_records(self.root))
        record = next(item for item in report if item["source_id"] == row["source_id"])
        self.assertEqual(record["image_status"], "APPROVED_WORKINGLIST_IMAGE")
        self.assertTrue(record["embedded"])
        self.assertEqual(images[row["source_id"]], self.content)
        row["name"] = "Different Apple"
        row["identity_changed"] = True
        images, report = map_images(self.root, rows, assignments, visual_records(self.root))
        record = next(item for item in report if item["source_id"] == row["source_id"])
        self.assertEqual(record["image_status"], "APPROVED_ASSIGNMENT_INVALID")
        self.assertNotIn(row["source_id"], images)

    def test_uncertain_old_mappings_are_reported_without_guessing(self):
        original = [
            dict(original_code="00042", original_description="Old name", cell="A1", heading="Apple", issue=""),
            dict(original_code="00046", original_description="Hidden Apple", cell="A2", heading="Apple", issue=""),
            dict(original_code="123", original_description="Apple Gala", cell="A3", heading="Apple", issue=""),
            dict(original_code="99999", original_description="Unknown", cell="A4", heading="Apple", issue=""),
        ]
        changes, _ = comparisons(original, self.items, [])
        self.assertEqual([row["status"] for row in changes], [
            "CODE_ACTIVE_DESCRIPTION_DIFFERS_REVIEW", "CODE_ONLY_HIDDEN_OR_DELETED",
            "POSSIBLE_CODE_CHANGE_EXACT_NAME_REVIEW", "NOT_IN_CURRENT_SOURCE_UNRESOLVED",
        ])
        self.assertEqual(changes[0]["active_match_count"], 2)

    def test_existing_ai_references_remain_without_cashier_labels_but_rejections_stay_blank(self):
        path = self.root / "data/image_review.csv"
        with path.open(newline="") as file:
            reviews = list(csv.DictReader(file))
        ai = next(row for row in reviews if row["plu"] == "00045")
        entries = [dict(idx=row["idx"], book="Fruit", plu=row["plu"], name=row["name"],
                        image="reference.png",
                        source="AI Generated" if row["idx"] == ai["idx"] else "Photo")
                   for row in reviews]
        entry_reviews = {row["idx"]: row for row in entries}
        with (self.root / "data/entries.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(entries[0]))
            writer.writeheader()
            writer.writerows(entries)
        for verdict in ("Approximate", "Rejected"):
            with self.subTest(verdict=verdict):
                ai["verdict"] = verdict
                with path.open("w", newline="") as file:
                    legacy_reviews = [
                        dict(entry_reviews[row["idx"]], verdict=row["verdict"],
                             note=row.get("note", ""))
                        for row in reviews
                    ]
                    writer = csv.DictWriter(file, fieldnames=list(legacy_reviews[0]))
                    writer.writeheader()
                    writer.writerows(legacy_reviews)
                assignments = read_assignments(self.root / "data/picklist_assignments.json")
                rows, _ = produce_catalog(self.items, assignments)
                images, report = map_images(self.root, rows, assignments, visual_records(self.root))
                record = next(row for row in report if row["plu"] == "00045")
                self.assertTrue(record["embedded"])
                self.assertEqual(record["image_status"], "LEGACY_PREAPPROVED_IMAGE")
                self.assertEqual(record["image_approval_status"], "APPROVED_LEGACY")
                self.assertEqual(record["legacy_original_verdict"], verdict)
                self.assertEqual(record["image_source"], "AI Generated")
                self.assertEqual(record["visual_verdict"], "APPROVED_LEGACY")
                self.assertIn("pre-approved", record["details"])
                donor, coordinates, _ = quick_sheet(rows, images, True)
                workbook = load_workbook(io.BytesIO(donor))
                self.addCleanup(workbook.close)
                entry = next(row for row in coordinates if row["plu"] == "00045")
                self.assertIsNone(workbook["Produce"][entry["image_cell"]].value)

    def test_pagination_never_orphans_a_heading_or_loses_duplicate_records(self):
        rows = [dict(display_section="Apples" if i < 80 else "Melons", source_id=str(i))
                for i in range(130)]
        layout = layout_rows(rows)
        self.assertEqual([entry["record"]["source_id"] for entry in layout if entry["kind"] == "product"],
                         [str(i) for i in range(130)])
        for index, entry in enumerate(layout):
            if entry["kind"] == "heading":
                self.assertEqual(layout[index + 1]["kind"], "product")
                self.assertEqual(layout[index + 1]["block"], entry["block"])
        self.assertTrue(any(entry["block"] >= 3 for entry in layout))

    def test_validation_detects_unrelated_package_changes(self):
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        images, report = map_images(self.root, rows, assignments, visual_records(self.root))
        donor, coordinates, _ = quick_sheet(rows, images, False)
        output = self.root / "changed.xlsx"
        replace_produce(self.binder, donor, output)
        validate_package(self.binder, output, coordinates, images, False)
        corrupted = self.root / "corrupted.xlsx"
        with zipfile.ZipFile(output) as source, zipfile.ZipFile(corrupted, "w") as target:
            for entry in source.infolist():
                target.writestr(entry, b"<changed/>" if entry.filename == "customXml/untouched.xml"
                                else source.read(entry.filename))
        with self.assertRaisesRegex(ValueError, "unrelated workbook part"):
            validate_package(self.binder, corrupted, coordinates, images, False)

    def test_broken_xml_and_missing_source_never_produce_a_binder(self):
        (self.root / "sources/plu/PickList.xml").write_bytes(b"<broken>")
        with self.assertRaisesRegex(ValueError, "cannot parse"):
            generate(self.root, self.binder, self.output)
        self.assertEqual(list(self.output.glob("*.xlsx")), [])
        with self.assertRaisesRegex(ValueError, "missing original"):
            generate(self.root, self.root / "missing.xlsx", self.root / "other-output")

    def write_ai_manifest(self, panels):
        folder = self.root / "data/review-references"
        folder.mkdir(exist_ok=True)
        (folder / "sheet.png").write_bytes(self.content)
        manifest = dict(schema_version=1, source="data/review-references/sheet.png",
                        source_sha256=sha(self.content), source_size=[600, 500],
                        origin="Owner-supplied AI illustration", review_note="Review only", panels=panels)
        path = folder / "additional-36-ai.json"
        path.write_text(json.dumps(manifest))
        return path

    def ai_panel(self, number, **changes):
        item = self.items[number]
        return dict(plu=item["plu"], product=item["name"], box=[10, 10, 190, 160],
                    decision="REVIEW_REFERENCE", **changes)

    def test_new_ai_reference_replaces_blank_with_exact_crop_without_approving_registry(self):
        self.write_ai_manifest([self.ai_panel(3), self.ai_panel(8)])
        before = (self.root / "data/picklist_assignments.json").read_bytes()
        summary = generate(self.root, self.binder, self.output)
        self.assertEqual(summary["new_ai_crops_embedded"], 2)
        self.assertEqual(summary["embedded_references"], 7)
        self.assertEqual(summary["production_publication"], "BLOCKED")
        self.assertEqual((self.root / "data/picklist_assignments.json").read_bytes(), before)
        with (self.output / "PHOTO_MAPPING.csv").open(encoding="utf-8-sig", newline="") as file:
            audit = list(csv.DictReader(file))
        reference = next(row for row in audit if row["plu"] == "00044")
        self.assertEqual(reference["image_status"], "SUPPLIED_AI_CROP_REVIEW")
        self.assertEqual(reference["rights_status"], "NOT_VERIFIED")
        self.assertEqual(reference["photograph_status"], "AI_ILLUSTRATION_NOT_PHOTOGRAPH")
        self.assertEqual((reference["width"], reference["height"]), ("180", "150"))
        organic = next(row for row in audit if row["plu"] == "00049")
        self.assertEqual(organic["organic_badge"], "True")
        self.assertNotEqual(organic["embedded_sha256"], organic["original_sha256"])

    def test_ai_crops_reject_stale_identity_ambiguous_duplicates_and_rejected_panels(self):
        path = self.write_ai_manifest([self.ai_panel(3)])
        rows = [self.items[3], dict(self.items[3], source_id="another-occurrence")]
        refs, audit = load_references(self.root, rows)
        self.assertEqual(refs, {})
        self.assertEqual(audit[0]["status"], "AMBIGUOUS_DUPLICATE_IDENTITY")
        manifest = json.loads(path.read_text())
        manifest["panels"][0]["source_id"] = self.items[3]["source_id"]
        path.write_text(json.dumps(manifest))
        refs, _ = load_references(self.root, rows)
        self.assertEqual(set(refs), {self.items[3]["source_id"]})
        refs, audit = load_references(self.root, [dict(self.items[3], name="Changed product")])
        self.assertEqual(refs, {})
        self.assertEqual(audit[0]["status"], "WORKING_IDENTITY_REVIEW_REQUIRED")
        manifest["panels"][0]["decision"] = "REJECTED"
        path.write_text(json.dumps(manifest))
        refs, audit = load_references(self.root, self.items)
        self.assertEqual(refs, {})
        self.assertEqual(audit[0]["status"], "REJECTED")
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        _, report = map_images(self.root, rows, assignments, visual_records(self.root))
        record = next(row for row in report if row["plu"] == self.items[3]["plu"])
        self.assertIn("New AI panel excluded:", record["details"])

    def test_working_identity_change_requires_fresh_ai_reference_review(self):
        self.write_ai_manifest([self.ai_panel(3)])
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        original = next(row for row in rows if row["source_position"] == 4)
        changed = dict(original, name="WorkingList canonical name",
                       source_id="working-identity-123",
                       source_ids=[original["source_id"]], identity_changed=True)
        references, audit = load_references(self.root, [changed])
        self.assertEqual(references, {})
        self.assertEqual(audit[0]["status"], "WORKING_IDENTITY_REVIEW_REQUIRED")

    def test_small_ai_crops_keep_proportional_badge_without_changing_legacy_renderer(self):
        panel = self.ai_panel(8)
        panel["box"] = [0, 0, 60, 50]
        self.write_ai_manifest([panel])
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        references, _ = load_references(self.root, rows)
        images, _ = map_images(self.root, rows, assignments, visual_records(self.root))
        source_id = self.items[8]["source_id"]
        content = references[source_id]["content"]
        self.assertEqual(images[source_id], render_watermark(content, minimum_side=1))
        self.assertNotEqual(images[source_id], render_watermark(content))
        self.assertEqual(Image.open(io.BytesIO(images[source_id])).size, (60, 50))

    def test_ai_crop_checksums_bounds_and_exact_text_are_enforced(self):
        path = self.write_ai_manifest([self.ai_panel(3)])
        original = json.loads(path.read_text())
        for field, value, message in (
                ("source_sha256", "changed", "checksum"),
                ("source_size", [1, 1], "dimensions")):
            with self.subTest(field=field):
                manifest = dict(original, **{field: value})
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, message):
                    load_references(self.root, self.items)
        for box in ([-1, 0, 100, 100], [0, 0, 601, 100], [100, 0, 0, 100], [0, 0, 1.5, 2]):
            manifest = json.loads(json.dumps(original))
            manifest["panels"][0]["box"] = box
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "crop box"):
                load_references(self.root, self.items)
        path.write_text(json.dumps(original))
        refs, audit = load_references(self.root, [dict(self.items[3], plu="44")])
        self.assertEqual(refs, {})
        self.assertEqual(audit[0]["status"], "NO_ACTIVE_EXACT_IDENTITY")

    def test_review_booklets_include_exact_entries_and_images_without_cashier_metadata(self):
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        rows, _ = produce_catalog(self.items, assignments)
        self.write_ai_manifest([self.ai_panel(3)])
        images, _ = map_images(self.root, rows, assignments, visual_records(self.root))
        non_produce = dict(self.items[7], book="Non-produce", section="Misc",
                           organic=False, duplicate_count=1)
        vegetable = dict(rows[0], source_id="vegetable-fixture", book="Vegetable", plu="00071",
                         name="Vegetable", section="Vegetables", organic=False, duplicate_count=1)
        results = build_review_booklets(
            self.root / "booklets", rows + [non_produce, vegetable], images, assignments, self.digest)
        self.assertEqual(results["Fruit"]["records"], len(rows))
        self.assertEqual(results["Non-produce"]["images"], 0)
        self.assertTrue(all(result["cashier_image_labels_absent"] for result in results.values()))
        self.assertEqual(len(list((self.root / "booklets").glob("*.docx"))), 3)
        self.assertEqual(len(list((self.root / "booklets").glob("*.xlsx"))), 3)

    def test_standalone_review_reports_available_binder_and_rejects_changed_original(self):
        registry_path = self.root / "data/picklist_assignments.json"
        registry = json.loads(registry_path.read_text())
        registry["assignments"][1].update(book="Vegetable", section="Vegetables")
        registry_path.write_text(json.dumps(registry))
        reports = self.root / "current/review-booklets"
        reports.mkdir(parents=True)
        for name in ("DUPLICATE_PLU_CLASSIFICATIONS.csv", "DUPLICATE_PLU_CLASSIFICATION_REVIEW.md"):
            (reports / name).write_text("Fixture decision report\n")
        missing = build_working_list_review(self.root, self.output)
        self.assertEqual(missing["complete_binder_regeneration"]["status"], "BLOCKED_MISSING_ORIGINAL")
        binder_path = self.root / "sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx"
        binder_path.parent.mkdir(exist_ok=True)
        binder_path.write_bytes(self.binder.read_bytes())
        with patch("review_booklets.ORIGINAL_BINDER_SHA256", sha(self.binder.read_bytes())):
            output = self.root / "available-review"
            available = build_working_list_review(self.root, output)
            self.assertEqual(available["complete_binder_regeneration"]["status"], "ORIGINAL_AVAILABLE_NOT_RUN")
            self.assertIn("available and checksum-verified", (output / "BUILD_NOTES.txt").read_text())
            self.assertNotIn("workbook is missing", (output / "BUILD_NOTES.txt").read_text())
            self.assertIn(str(binder_path.relative_to(self.root)), (output / "SHA256SUMS.txt").read_text())
            binder_path.write_bytes(b"Changed original")
            with self.assertRaisesRegex(ValueError, "binder checksum differs"):
                build_working_list_review(self.root, self.root / "changed-review")
        self.assertFalse((self.root / "changed-review").exists())

    def test_supplier_photos_override_ai_with_permission_and_checksum_evidence_only(self):
        self.write_ai_manifest([self.ai_panel(3)])
        folder = self.root / "data/review-references/buck-brand"
        folder.mkdir()
        (folder / "test.png").write_bytes(self.content)
        (folder / "IMAGE_INVENTORY.json").write_text(json.dumps([
            dict(filename="test.png", width=600, height=500, sha256=sha(self.content))]))
        path = folder.parent / "buck-brand.json"
        manifest = dict(schema_version=1, source_url="https://example.test/source.pdf",
                        pdf_sha256="source-digest", attribution="Supplier copyright",
                        rights_status="OWNER_CONFIRMED_PERMISSION",
                        rights_evidence="Owner confirmed permission for binders and repository",
                        note="Review only", mappings=[
                            dict(plu=self.items[3]["plu"], product=self.items[3]["name"],
                                 label="Exact product", asset="test.png")])
        path.write_text(json.dumps(manifest))
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        before = (self.root / "data/picklist_assignments.json").read_bytes()
        rows, _ = produce_catalog(self.items, assignments)
        images, report = map_images(self.root, rows, assignments, visual_records(self.root))
        record = next(row for row in report if row["plu"] == self.items[3]["plu"])
        self.assertEqual(record["image_status"], "SUPPLIER_REFERENCE_REVIEW")
        self.assertEqual(record["rights_status"], "OWNER_CONFIRMED_PERMISSION")
        self.assertEqual(record["photograph_status"], "SUPPLIER_PUBLISHED_PHOTO")
        self.assertEqual(images[self.items[3]["source_id"]], self.content)
        self.assertEqual(before, (self.root / "data/picklist_assignments.json").read_bytes())
        refs, _ = load_references(self.root, [dict(self.items[3], name="New identity")])
        self.assertNotIn(self.items[3]["source_id"], refs)
        _, audit = load_references(self.root, [dict(self.items[3], name="New identity")])
        self.assertEqual(audit[0]["status"], "WORKING_IDENTITY_REVIEW_REQUIRED")
        manifest["rights_status"] = "UNKNOWN"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "permission"):
            load_references(self.root, rows)
        manifest["rights_status"] = "OWNER_CONFIRMED_PERMISSION"
        path.write_text(json.dumps(manifest))
        jpeg = io.BytesIO()
        Image.open(io.BytesIO(self.content)).save(jpeg, format="JPEG")
        # PDF-extracted JPEGs may lack the JFIF header required by python-docx.
        original = jpeg.getvalue()
        segment_end = 4 + int.from_bytes(original[4:6], "big")
        content = original[:2] + original[segment_end:]
        (folder / "test.png").write_bytes(content)
        (folder / "IMAGE_INVENTORY.json").write_text(json.dumps([
            dict(filename="test.png", width=600, height=500, sha256=sha(content))]))
        refs, _ = load_references(self.root, rows)
        from docx.image.image import Image as DocxImage
        decoded = refs[self.items[3]["source_id"]]["content"]
        self.assertEqual(DocxImage.from_file(io.BytesIO(decoded)).px_width, 600)
        self.assertEqual(Image.open(io.BytesIO(decoded)).tobytes(),
                         Image.open(io.BytesIO(content)).tobytes())
        (folder / "test.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_references(self.root, rows)


if __name__ == "__main__":
    unittest.main()
