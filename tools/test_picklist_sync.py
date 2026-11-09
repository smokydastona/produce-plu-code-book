import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from docx import Document
from PIL import Image
from openpyxl import load_workbook

from picklist_catalog import read_assignments, read_picklist
from sync_picklist import (BOOKS, build_documents, original_image, reconcile,
                           reviewed_image, safe_asset, booklet_order, verify_pdfs,
                           build_workbooks, verify_workbooks)
from approve_picklist_image import approve
from check_image_uniqueness import image_fingerprint
from organic_watermarks import render_watermark


class PickListSyncChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sources/plu").mkdir(parents=True)
        (self.root / "data").mkdir()
        self.source = self.root / "sources/plu/PickList.xml"
        self.output = self.root / "reports"
        self.output.mkdir()
        self.image = self.root / "data/apple.png"
        Image.new("RGB", (600, 500), "red").save(self.image)
        self.write_source([("03283", "Honeycrisp Apple", True)])
        self.items, _ = read_picklist(self.source)
        self.assignment = self.approved_assignment(self.items[0])
        self.write_assignments([self.assignment])

    def write_source(self, values, utf16=True):
        root = ET.Element("PickList")
        items = ET.SubElement(root, "Items")
        for value in values:
            plu, name, visible = value[:3]
            deleted = value[3] if len(value) > 3 else False
            item = ET.SubElement(items, "Item", UPC=plu)
            ET.SubElement(item, "Department").text = "001"
            ET.SubElement(item, "IsVisible").text = str(visible)
            ET.SubElement(item, "DeleteThisItem").text = str(deleted)
            languages = ET.SubElement(item, "Languages")
            english = ET.SubElement(languages, "Language", LCID="0409")
            ET.SubElement(english, "Description").text = name
        self.source.write_bytes(ET.tostring(root, encoding="utf-16" if utf16 else "utf-8"))

    def approved_assignment(self, item):
        return dict(
            source_id=item["source_id"], book="Fruit", section="Apples", image="data/apple.png",
            image_mode="PHOTO", reviewed_plu=item["plu"], reviewed_product=item["name"],
            image_sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
            photographic_origin="VERIFIED_PHOTO", visual_approval_status="APPROVED",
            rights_verification_status="VERIFIED",
            provenance=dict(
                creator="Test photographer", license="CC0",
                source_page_url="https://example.org/apple", original_image_url="https://example.org/apple.png",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                attribution="Test photographer / CC0", changes="None",
                rights_evidence="Test fixture; no real-world approval",
            ),
        )

    def write_assignments(self, rows):
        (self.root / "data/picklist_assignments.json").write_text(
            json.dumps(dict(schema_version=1, assignments=rows)), encoding="utf-8")

    def test_exact_strings_duplicates_and_visibility_are_preserved(self):
        self.write_source([
            ("00042", "Owner's  Exact Name", True),
            ("00042", "Owner's  Exact Name", True),
            ("00042", "Hidden", False), ("55", "Deleted", True, True),
        ])
        before = self.source.read_bytes()
        items, digest = read_picklist(self.source)
        self.assertEqual(items[0]["plu"], "00042")
        self.assertEqual(items[0]["name"], "Owner's  Exact Name")
        self.assertEqual([item["occurrence"] for item in items[:2]], [1, 2])
        self.assertNotEqual(items[0]["source_id"], items[1]["source_id"])
        self.assertEqual([item["included"] for item in items], [True, True, False, False])
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(digest, hashlib.sha256(before).hexdigest())

    def test_reordering_and_encoding_changes_do_not_break_identity(self):
        self.write_source([("1", "Apple", True), ("2", "Pear", True)])
        before = {item["plu"]: item["source_id"] for item in read_picklist(self.source)[0]}
        self.write_source([("2", "Pear", True), ("1", "Apple", True)], utf16=False)
        after = {item["plu"]: item["source_id"] for item in read_picklist(self.source)[0]}
        self.assertEqual(before, after)

    def test_new_and_renamed_products_are_not_automatically_approved(self):
        self.write_source([
            ("03283", "Renamed Apple", True), ("42", "New Variety", True),
        ])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["missing_image_requests"], 2)
        self.assertEqual(summary["inactive_assignments"], 1)
        self.assertEqual([row["name"] for row in rows], ["Renamed Apple", "New Variety"])
        self.assertTrue(all("APPROVED_IMAGE_REQUIRED" in row["blockers"] for row in rows))
        requests = (self.output / "IMAGE_REQUESTS.csv").read_text(encoding="utf-8-sig")
        self.assertIn("New Variety", requests)

    def test_code_changes_require_fresh_assignment_not_description_fallback(self):
        self.write_source([("99999", "Honeycrisp Apple", True)])
        _, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["missing_image_requests"], 1)
        self.assertEqual(summary["inactive_assignments"], 1)

    def test_hidden_and_deleted_items_leave_active_output_without_deleting_assets(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", False), ("42", "Visible", True),
            ("43", "Deleted", True, True),
        ])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual([row["plu"] for row in rows], ["42"])
        self.assertEqual(summary["excluded_records"], 2)
        self.assertTrue(self.image.exists())
        self.assertIn("03283", (self.output / "INACTIVE_ASSIGNMENTS.csv").read_text())

    def test_full_candidate_requests_follow_xml_and_skip_only_reviewed_code_only(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", True), ("00042", "New Apple", True),
            ("00042", "New Apple", True), ("43", "Code Only", True),
            ("44", "Unreviewed Code Only", True), ("45", "Hidden", False),
            ("46", "Deleted", True, True),
        ])
        items, _ = read_picklist(self.source)
        code_only = self.approved_assignment(items[3])
        code_only.update(book="Non-produce", image="", image_mode="CODE_ONLY",
                         code_only_approved=True)
        unreviewed = self.approved_assignment(items[4])
        unreviewed.update(book="Non-produce", image="", image_mode="CODE_ONLY",
                          code_only_approved=False)
        self.write_assignments([self.assignment, code_only, unreviewed])
        source_before = self.source.read_bytes()
        reconcile(self.root, self.output)
        with (self.output / "ALL_IMAGE_REQUESTS.csv").open(encoding="utf-8-sig", newline="") as file:
            requests = list(csv.DictReader(file))
        self.assertEqual([row["plu"] for row in requests], ["03283", "00042", "00042", "44"])
        self.assertEqual([row["source_id"] for row in requests],
                         [items[i]["source_id"] for i in (0, 1, 2, 4)])
        self.assertEqual(requests[1]["name"], "New Apple")
        self.assertEqual(self.source.read_bytes(), source_before)

    def test_approved_images_build_from_current_source_without_editing_it(self):
        before = self.source.read_bytes()
        rows, images, assignments, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["status"], "READY_TO_BUILD")
        build_documents(self.root, self.output, rows, images, assignments, summary["source_sha256"])
        fruit = Document(self.output / (BOOKS["Fruit"] + ".docx"))
        cell = fruit.tables[0].cell(0, 0)
        self.assertIn("PLU: 03283", cell.text)
        self.assertIn("Honeycrisp Apple", cell.text)
        self.assertEqual(len(fruit.inline_shapes), 1)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue((self.output / "PHOTO_ATTRIBUTIONS.csv").exists())

    def test_blocked_cli_never_creates_booklets_and_never_touches_current(self):
        current = self.root / "current/booklets"
        current.mkdir(parents=True)
        sentinel = current / "previous.pdf"
        sentinel.write_bytes(b"last published")
        self.assignment["rights_verification_status"] = "NOT_VERIFIED"
        self.write_assignments([self.assignment])
        script = Path(__file__).with_name("sync_picklist.py")
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(self.root),
             "--output", str(self.root / "staging")], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no booklets were published", result.stderr)
        self.assertEqual(list((self.root / "staging").glob("*.docx")), [])
        self.assertEqual(list((self.root / "staging").glob("*.xlsx")), [])
        self.assertEqual(sentinel.read_bytes(), b"last published")
        second = subprocess.run(
            [sys.executable, str(script), "--root", str(self.root),
             "--output", str(self.root / "staging")], capture_output=True, text=True)
        self.assertIn("output must be empty", second.stderr)

    def test_duplicate_photos_across_conventional_entries_block_build(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("42", "Other Apple", True)])
        items, _ = read_picklist(self.source)
        self.write_assignments([self.approved_assignment(item) for item in items])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertTrue(all("PROHIBITED_IMAGE_REUSE" in row["blockers"] for row in rows))

    def test_matching_organic_pair_renders_same_upper_left_badge(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("903283", "Organic Apple", True)])
        items, _ = read_picklist(self.source)
        first, second = [self.approved_assignment(item) for item in items]
        second["reuse_from_source_id"] = first["source_id"]
        self.write_assignments([first, second])
        rows, images, assignments, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["status"], "READY_TO_BUILD")
        build_documents(self.root, self.output, rows, images, assignments, summary["source_sha256"])
        doc = Document(self.output / (BOOKS["Fruit"] + ".docx"))
        picture = doc.inline_shapes[1]
        relationship = picture._inline.graphic.graphicData.pic.blipFill.blip.embed
        content = doc.part.related_parts[relationship].blob
        with Image.open(io.BytesIO(content)) as image, Image.open(self.image) as original:
            self.assertNotEqual(image.crop((0, 0, 180, 180)).tobytes(),
                                original.crop((0, 0, 180, 180)).tobytes())
            self.assertEqual(image.crop((200, 200, 600, 500)).tobytes(),
                             original.crop((200, 200, 600, 500)).tobytes())

    def placement_rows(self, values):
        return [
            dict(source_id=str(index), source_position=index, plu=plu, name=name,
                 book=book, section=section, organic="organic" in name.lower())
            for index, (plu, name, book, section) in enumerate(values, 1)
        ]

    def test_organics_follow_all_conventional_sizes_and_duplicates(self):
        rows = self.placement_rows([
            ("94013", "Organic Apples Gala", "Fruit", "Organic Fruit"),
            ("4013", "Apples Gala Small", "Fruit", "Apples"),
            ("4020", "Apples Golden Delicious", "Fruit", "Apples"),
            ("4135", "Apples Gala Large", "Fruit", "Apples"),
            ("4013", "Apples Gala Small", "Fruit", "Apples"),
            ("94135", "Organic Gala Apples", "Fruit", "Organic Fruit"),
        ])
        before = json.dumps(rows)
        result = booklet_order(rows, {})
        self.assertEqual([row["source_id"] for row in result], ["2", "4", "5", "1", "6", "3"])
        self.assertTrue(all(row["display_section"] == "Apples" for row in result))
        self.assertEqual(result[3]["counterpart_source_ids"], "2;4;5")
        self.assertEqual([row["booklet_position"] for row in result], list(range(1, 7)))
        self.assertEqual(json.dumps(rows), before)

    def test_unmatched_and_ambiguous_organics_stay_in_normal_category_and_are_flagged(self):
        rows = self.placement_rows([
            ("94769", "Organic Squash Stripetti", "Vegetable", "Organic Vegetables"),
            ("4769", "Kabocha", "Vegetable", "Squash"),
            ("1", "Lettuce Romaine", "Vegetable", "Lettuce"),
            ("2", "Lettuce Romaine", "Vegetable", "Leafy Greens"),
            ("3", "Organic Lettuce Romaine", "Vegetable", "Organic Vegetables"),
        ])
        result = booklet_order(rows, {})
        self.assertEqual({row["source_id"] for row in result}, {"1", "2", "3", "4", "5"})
        organic_rows = [row for row in result if row["organic"]]
        self.assertTrue(all(row["placement_status"] == "PLACEMENT_REVIEW_REQUIRED" for row in organic_rows))
        self.assertEqual({row["display_section"] for row in organic_rows}, {"Squash", "Lettuce"})
        self.assertTrue(all(not row["counterpart_source_ids"] for row in organic_rows))
        self.assertEqual([row["plu"] for row in result[:2]], ["4769", "94769"])

    def test_reviewed_placement_is_independent_of_photo_reuse_and_never_crosses_books(self):
        rows = self.placement_rows([
            ("94020", "Organic Apples Golden Delicious", "Fruit", "Organic Fruit"),
            ("4020", "Apples Gold Delicious Large", "Fruit", "Apples"),
            ("9", "Apples Golden Delicious", "Vegetable", "Specialty Vegetables"),
        ])
        assignments = {"1": {"placement_after_source_id": "2"}}
        result = booklet_order(rows, assignments)
        self.assertEqual([row["source_id"] for row in result], ["2", "1", "3"])
        self.assertEqual(result[1]["placement_status"], "REVIEWED_COUNTERPART")
        self.assertNotIn("reuse_from_source_id", assignments["1"])
        with self.assertRaisesRegex(ValueError, "same booklet"):
            booklet_order(rows, {"1": {"placement_after_source_id": "3"}})

    def test_orphan_organics_with_no_conventional_entries_keep_all_records(self):
        rows = self.placement_rows([
            ("00042", "Organic Apple Unknown", "Fruit", "Organic Fruit"),
            ("00042", "Organic Apple Unknown", "Fruit", "Organic Fruit"),
            ("43", "Organic Unrecognized Product", "Fruit", "Organic Fruit"),
            ("44", "Ice", "Non-produce", "Ice"),
        ])
        result = booklet_order(rows, {})
        self.assertEqual([row["plu"] for row in result], ["00042", "00042", "43", "44"])
        self.assertEqual([row["display_section"] for row in result], ["Apples", "Apples", "Fruit", "Ice"])
        self.assertEqual(result[-1]["booklet_position"], 1)
        self.assertEqual(result[-1]["placement_status"], "SOURCE_ORDER")

    def test_order_report_and_docx_use_same_order_without_changing_xml(self):
        self.write_source([
            ("903283", "Organic Honeycrisp Apple", True),
            ("03283", "Honeycrisp Apple Large", True),
            ("42", "Other Apple", True),
            ("00043", "Honeycrisp Apple Small", True),
        ])
        items, _ = read_picklist(self.source)
        assignments = [self.approved_assignment(item) for item in items]
        assignments[0]["section"] = "Organic Fruit"
        self.write_assignments(assignments)
        before = self.source.read_bytes()
        rows, images, registry, summary = reconcile(self.root, self.output)
        # Layout fixtures do not grant publication approval to reused test images.
        self.assertEqual(summary["status"], "BLOCKED")
        build_documents(self.root, self.output, rows, images, registry, summary["source_sha256"])
        with (self.output / "BOOKLET_ORDER.csv").open(encoding="utf-8-sig", newline="") as file:
            report = list(csv.DictReader(file))
        self.assertEqual([row["plu"] for row in report], ["03283", "00043", "903283", "42"])
        fruit = Document(self.output / (BOOKS["Fruit"] + ".docx"))
        cells = [cell for table in fruit.tables for row in table.rows for cell in row.cells
                 if cell.text.startswith("PLU: ")]
        self.assertEqual([cell.paragraphs[0].text for cell in cells],
                         ["PLU: " + row["plu"] for row in report])
        self.assertTrue(all("Section: Apples" in cell.text for cell in cells))
        self.assertEqual(self.source.read_bytes(), before)

    def test_pdf_verification_requires_interleaved_sequence_not_xml_order(self):
        from types import SimpleNamespace

        rows = self.placement_rows([
            ("900042", "Organic Apple", "Fruit", "Organic Fruit"),
            ("00042", "Apple", "Fruit", "Apples"),
        ])
        page = SimpleNamespace(mediabox=SimpleNamespace(width=792, height=612),
                               extract_text=lambda: "PLU: 00042\nPLU: 900042")
        empty = SimpleNamespace(pages=[])
        readers = iter([SimpleNamespace(pages=[page]), empty, empty])
        with patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=lambda path: next(readers))}):
            verify_pdfs(self.output, rows, {})
        page.extract_text = lambda: "PLU: 900042\nPLU: 00042"
        with patch.dict(sys.modules, {"pypdf": SimpleNamespace(
                PdfReader=lambda path: SimpleNamespace(pages=[page]))}):
            with self.assertRaisesRegex(ValueError, "booklet order"):
                verify_pdfs(self.output, rows, {})

    def test_excel_preserves_strings_duplicates_order_photos_and_credits(self):
        self.write_source([
            ("900042", "Organic Apple Gala", True), ("00042", "Apple Gala", True),
            ("00042", "Apple Gala", True), ("00043", "=Unusual Product", True),
        ])
        items, digest = read_picklist(self.source)
        assignments = {item["source_id"]: self.approved_assignment(item) for item in items}
        assignments[items[0]["source_id"]]["section"] = "Organic Fruit"
        assignments[items[0]["source_id"]]["provenance"]["creator"] = "=Literal Creator"
        rows = [dict(item, book="Fruit", section=assignments[item["source_id"]]["section"],
                     organic=index == 0) for index, item in enumerate(items)]
        images = {item["source_id"]: self.image.read_bytes() for item in items}
        before = self.source.read_bytes()
        build_workbooks(self.output, rows, images, assignments, digest)
        verify_workbooks(self.output, rows, assignments, digest)
        workbook = load_workbook(self.output / (BOOKS["Fruit"] + ".xlsx"))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook.sheetnames, ["Booklet", "Photo credits"])
        sheet = workbook["Booklet"]
        self.assertEqual([sheet.cell(number, 1).value for number in range(5, 9)],
                         ["00042", "00042", "900042", "00043"])
        self.assertEqual(sheet["B8"].value, "=Unusual Product")
        self.assertEqual(sheet["B8"].data_type, "s")
        self.assertEqual(sheet["A5"].number_format, "@")
        self.assertEqual(sheet["A5"].data_type, "s")
        self.assertEqual(sheet["C7"].value, "Apples")
        self.assertEqual(sheet["D7"].value, "YES")
        self.assertEqual(sheet.freeze_panes, "B5")
        self.assertEqual(sheet.auto_filter.ref, "A4:F8")
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(str(sheet.page_setup.paperSize), sheet.PAPERSIZE_LETTER)
        self.assertEqual(sheet["B2"].value, digest)
        self.assertEqual(len(sheet._images), 4)
        for index, picture in enumerate(sheet._images):
            self.assertEqual(picture.anchor._from.row, 4 + index)
            self.assertEqual(picture.anchor._from.col, 4)
            expected = render_watermark(self.image.read_bytes()) if index == 2 else self.image.read_bytes()
            self.assertEqual(image_fingerprint(io.BytesIO(picture._data())),
                             image_fingerprint(io.BytesIO(expected)))
        credits = workbook["Photo credits"]
        self.assertEqual(credits.max_row, 5)
        self.assertEqual(credits["A4"].value, "900042")
        self.assertEqual(credits["C4"].value, "=Literal Creator")
        self.assertEqual(credits["C4"].data_type, "s")
        self.assertIn("pink organic badge added", credits["I4"].value)
        self.assertEqual(credits["J4"].value, assignments[items[0]["source_id"]]["provenance"]["rights_evidence"])
        self.assertEqual(self.source.read_bytes(), before)

    def test_excel_verification_rejects_changed_values_formulas_and_source_checksum(self):
        rows, images, assignments, summary = reconcile(self.root, self.output)
        for change, message in (
                ("code", "entries differ"), ("formula", "literal text"), ("digest", "checksum")):
            with self.subTest(change=change):
                build_workbooks(self.output, rows, images, assignments, summary["source_sha256"])
                path = self.output / (BOOKS["Fruit"] + ".xlsx")
                workbook = load_workbook(path)
                if change == "code":
                    workbook["Booklet"]["A5"] = 3283
                elif change == "formula":
                    workbook["Photo credits"]["C2"] = "=1+1"
                else:
                    workbook.properties.identifier = "picklist-sha256:stale"
                workbook.save(path)
                workbook.close()
                with self.assertRaisesRegex(ValueError, message):
                    verify_workbooks(self.output, rows, assignments, summary["source_sha256"])

    def test_excel_rejects_text_that_would_be_silently_truncated(self):
        rows, images, assignments, summary = reconcile(self.root, self.output)
        rows[0]["name"] = "x" * 32768
        with self.assertRaisesRegex(ValueError, "Excel's cell limit"):
            build_workbooks(self.output, rows, images, assignments, summary["source_sha256"])

    def test_cli_builds_three_excel_versions_including_code_only_and_empty_books(self):
        self.assignment.update(book="Non-produce", image="", image_mode="CODE_ONLY",
                               code_only_approved=True)
        self.write_assignments([self.assignment])
        before = self.source.read_bytes()
        staging = self.root / "staging"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("sync_picklist.py")),
             "--root", str(self.root), "--output", str(staging)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(staging.glob("*.xlsx"))), 3)
        self.assertEqual(len(list(staging.glob("*.docx"))), 3)
        self.assertTrue(json.loads((staging / "BUILD_VERIFIED.json").read_text())["workbooks_verified"])
        workbook = load_workbook(staging / (BOOKS["Non-produce"] + ".xlsx"))
        self.addCleanup(workbook.close)
        self.assertEqual(workbook["Booklet"]["A5"].value, "03283")
        self.assertIn("CODE-ONLY", workbook["Booklet"]["F5"].value)
        self.assertEqual(len(workbook["Booklet"]._images), 0)
        self.assertEqual(workbook["Photo credits"].max_row, 1)
        self.assertEqual(self.source.read_bytes(), before)

    def test_catalog_only_never_creates_excel_or_docx_files(self):
        staging = self.root / "staging"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("sync_picklist.py")),
             "--root", str(self.root), "--output", str(staging), "--catalog-only"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(staging.glob("*.xlsx")), [])
        self.assertEqual(list(staging.glob("*.docx")), [])

    def test_organic_matching_is_explicit_not_guessed_from_codes(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("903283", "Organic Apple", True)])
        items, _ = read_picklist(self.source)
        first, second = [self.approved_assignment(item) for item in items]
        self.write_assignments([first, second])
        self.assertIn("PROHIBITED_IMAGE_REUSE", reconcile(self.root, self.output)[0][1]["blockers"])
        second["reuse_from_source_id"] = first["source_id"]
        self.write_assignments([first, second])
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_reviewer_metadata_and_original_file_are_both_required(self):
        self.assignment["rights_verification_status"] = "NOT_VERIFIED"
        self.assignment["image_sha256"] = "wrong"
        self.assignment["reviewed_product"] = "Different"
        _, _, _, errors = reviewed_image(self.root, self.items[0], self.assignment)
        for error in ("IMAGE_RIGHTS_NOT_VERIFIED", "IMAGE_CHECKSUM_MISMATCH",
                      "PRODUCT_IMAGE_REVIEW_REQUIRED"):
            self.assertIn(error, errors)

    def test_legacy_original_does_not_get_inferred_rights(self):
        with patch("sync_picklist.original_image", return_value=self.image.read_bytes()):
            self.assignment["provenance"] = {}
            self.assertIn("SUPPORTED_IMAGE_LICENCE_REQUIRED",
                          reviewed_image(self.root, self.items[0], self.assignment)[3])

    def test_non_produce_code_only_exception_requires_explicit_approval(self):
        self.assignment.update(book="Non-produce", image="", image_mode="CODE_ONLY",
                               code_only_approved=True)
        self.write_assignments([self.assignment])
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")
        self.assignment["code_only_approved"] = False
        self.write_assignments([self.assignment])
        self.assertIn("CODE_ONLY_APPROVAL_REQUIRED",
                      reconcile(self.root, self.output)[0][0]["blockers"])

    def test_empty_invalid_xml_and_duplicate_assignments_fail_explicitly(self):
        self.write_assignments([self.assignment, self.assignment])
        with self.assertRaisesRegex(ValueError, "duplicate assignment"):
            read_assignments(self.root / "data/picklist_assignments.json")
        self.source.write_bytes(b"<PickList>")
        with self.assertRaisesRegex(ValueError, "cannot parse"):
            read_picklist(self.source)
        self.write_source([])
        with self.assertRaisesRegex(ValueError, "contains no items"):
            read_picklist(self.source)

    def test_paths_outside_repository_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "out-of-repository"):
            safe_asset(self.root, "../outside.jpg")
        self.assertEqual(original_image(self.root, self.assignment), self.image.read_bytes())

    def candidate_metadata(self):
        metadata = dict(
            self.assignment["provenance"], plu=self.items[0]["plu"], product=self.items[0]["name"],
            sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(), width=600, height=500,
            approval_status="CANDIDATE",
        )
        self.image.with_suffix(".png.json").write_text(json.dumps(metadata))

    def test_explicit_approval_promotes_exact_product_with_persisted_evidence(self):
        self.candidate_metadata()
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        source_before = self.source.read_bytes()
        approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                digest, "Reviewed original creator declaration and licence", replace=True)
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        entry = assignments[self.items[0]["source_id"]]
        self.assertIn("data/images/approved/", entry["image"])
        image = self.root / entry["image"]
        self.assertTrue(image.with_suffix(image.suffix + ".json").is_file())
        self.assertEqual(entry["rights_verification_status"], "VERIFIED")
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_approval_rejects_stale_xml_wrong_products_and_unrequested_replacements(self):
        self.candidate_metadata()
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "changed since review"):
            approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                    "wrong", "Evidence", replace=True)
        with self.assertRaisesRegex(ValueError, "assignment exists"):
            approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                    digest, "Evidence")
        path = self.image.with_suffix(".png.json")
        metadata = json.loads(path.read_text())
        metadata["product"] = "Another product"
        path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "exact product"):
            approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                    digest, "Evidence", replace=True)

    def test_cli_will_not_approve_without_explicit_review_confirmations(self):
        script = Path(__file__).with_name("approve_picklist_image.py")
        result = subprocess.run([
            sys.executable, str(script), "--root", str(self.root), "--source-id", self.items[0]["source_id"],
            "--candidate", str(self.image), "--book", "Fruit", "--section", "Apples",
            "--expected-source-sha", "sha", "--rights-evidence", "Evidence",
        ], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit --approve-visual", result.stderr)


if __name__ == "__main__":
    unittest.main()
