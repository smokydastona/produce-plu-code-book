import csv
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Font
from PIL import Image

from build_till_binders import (FILENAMES, VISUALS, comparisons, generate, layout_rows,
                               map_images, produce_catalog, quick_sheet, replace_produce,
                               sha, validate_package, visual_records)
from picklist_catalog import read_picklist, read_assignments


class TillBinderChecks(unittest.TestCase):
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
        last = original.create_sheet("Hidden operations")
        last.sheet_state = "hidden"
        last["A1"] = "=Operational!B2"
        original.save(self.binder)
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
            self.assertEqual(workbook.sheetnames, ["Operational", "Produce", "Hidden operations"])
            self.assertEqual(workbook["Operational"]["B2"].value, "=SUM(A2:A3)")
            self.assertEqual(workbook["Operational"]["B2"].comment.text, "Keep this comment")
            self.assertEqual(str(workbook["Operational"].merged_cells), "A1:C1")
            self.assertEqual(len(workbook["Operational"]._images), 1)
            self.assertEqual(len(workbook["Operational"]._charts), 1)
            self.assertEqual(workbook["Hidden operations"].sheet_state, "hidden")
            self.assertTrue(summary["validations"][edition]["unrelated_package_parts_byte_identical"])
            self.assertEqual(len(workbook["Produce"]._images), 5 if edition == "photos" else 0)
            self.assertTrue(all(cell.data_type != "f" for row in workbook["Produce"] for cell in row))
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read("customXml/untouched.xml"), b"<custom>unchanged opaque object</custom>")
        self.assertEqual(self.binder.read_bytes(), before)
        self.assertEqual((self.root / "sources/plu/PickList.xml").read_bytes(), source_before)
        self.assertTrue((self.output / "PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt").is_file())
        with self.assertRaisesRegex(ValueError, "empty"):
            generate(self.root, self.binder, self.output)

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
        for verdict, embedded in (("Approximate", True), ("Rejected", False)):
            with self.subTest(verdict=verdict):
                ai["verdict"] = verdict
                with path.open("w", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=list(reviews[0]))
                    writer.writeheader()
                    writer.writerows(reviews)
                assignments = read_assignments(self.root / "data/picklist_assignments.json")
                rows, _ = produce_catalog(self.items, assignments)
                images, report = map_images(self.root, rows, assignments, visual_records(self.root))
                record = next(row for row in report if row["plu"] == "00045")
                self.assertEqual(record["embedded"], embedded)
                self.assertEqual(record["image_source"], "AI Generated")
                self.assertEqual(record["visual_verdict"], verdict)
                if embedded:
                    self.assertIn("uncertain", record["details"])
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


if __name__ == "__main__":
    unittest.main()
