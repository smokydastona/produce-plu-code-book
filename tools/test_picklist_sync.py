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
from image_display import display_image
from build_image_library import build_library, check_library, refresh_library
from verify_images import approved_library_pair
from working_list import read_working_list, rebuild_working_list


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
        self.items, self.digest = read_picklist(self.source)
        self.write_registry(self.items)
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

    def write_registry(self, items, decisions=None):
        baseline = [dict(source_id=row["source_id"], plu=row["plu"], name=row["name"],
                         department=row["department"], occurrence=row["occurrence"],
                         visible=row["visible"], deleted=row["deleted"]) for row in items]
        (self.root / "data/working_list_decisions.json").write_text(json.dumps(dict(
            schema_version=1, baseline_source_sha256=self.digest,
            baseline=baseline, decisions=decisions or [])), encoding="utf-8")

    def register_current_source(self, items):
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.write_registry(items)

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

    def test_new_hidden_source_identity_blocks_reconciliation(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", True), ("42", "New Hidden Item", False),
        ])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(rows[0]["blockers"], [])
        self.assertEqual(summary["reconciliation_review_records"], 1)
        self.assertEqual(summary["status"], "BLOCKED")

    def test_removed_decision_sources_block_even_without_a_current_matching_record(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", True), ("42", "Pear", True),
        ])
        items, _ = read_picklist(self.source)
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.write_registry(items, [dict(
            plu="03283", source_ids=[items[0]["source_id"]],
            canonical_name="Honeycrisp Apple", mode="STANDARDIZE",
        )])
        self.write_assignments([self.approved_assignment(items[1])])
        self.write_source([("42", "Pear", True)])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(rows[0]["blockers"], [])
        self.assertEqual(summary["reconciliation_review_decisions"], 1)
        self.assertEqual(summary["status"], "BLOCKED")

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

    def test_current_production_audit_matches_ready_build_without_legacy_booklets(self):
        output = self.root / "audit"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("audit_production.py")),
             "--root", str(self.root), "--output", str(output)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((output / "PRODUCTION_READINESS.json").read_text())
        self.assertEqual(report["status"], "AUTOMATED_CHECKS_PASSED_REQUIRES_RELEASE_REVIEW")
        self.assertEqual(report["picklist_sync"]["status"], "READY_TO_BUILD")
        self.assertNotIn("legacy_image_audit", report)

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
        self.write_source([("03283", "Honeycrisp Apple", True), ("903283", "Organic Honeycrisp Apple", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
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
        with Image.open(io.BytesIO(content)) as image:
            expected = Image.open(io.BytesIO(display_image(self.image.read_bytes())))
            self.addCleanup(expected.close)
            self.assertEqual(image.size, (500, 500))
            self.assertEqual((image.format, image.mode), ("JPEG", "RGB"))
            self.assertNotEqual(image.crop((0, 0, 150, 150)).tobytes(),
                                expected.crop((0, 0, 150, 150)).tobytes())
            self.assertEqual(image.crop((200, 200, 500, 500)).tobytes(),
                             expected.crop((200, 200, 500, 500)).tobytes())

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
        self.assertTrue(all("Section:" not in cell.text and "review" not in cell.text.lower()
                            for cell in cells))
        self.assertTrue((self.output / "PHOTO_ATTRIBUTIONS.csv").is_file())
        self.assertEqual(self.source.read_bytes(), before)

    def test_library_refresh_rejects_modified_managed_files(self):
        refresh_library(self.root)
        library = self.root / "sources/image-library"
        image = library / (self.items[0]["source_id"] + ".jpg")
        image.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "changed or missing"):
            refresh_library(self.root)
        with self.assertRaisesRegex(ValueError, "changed or missing"):
            check_library(self.root)
        self.assertEqual(image.read_bytes(), b"modified")

    def test_library_refresh_migrates_managed_pngs_to_jpegs_without_changing_originals(self):
        refresh_library(self.root)
        library = self.root / "sources/image-library"
        index = library / "IMAGE_LIBRARY.csv"
        with index.open(encoding="utf-8-sig", newline="") as file:
            row = next(csv.DictReader(file))
        jpeg = library / row["image"]
        png = jpeg.with_suffix(".png")
        original_before = self.image.read_bytes()
        with Image.open(jpeg) as image:
            image.save(png, format="PNG")
        metadata = json.loads(jpeg.with_suffix(".jpg.json").read_text())
        metadata["sha256"] = hashlib.sha256(png.read_bytes()).hexdigest()
        sidecar = png.with_suffix(".png.json")
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        row.update(image=png.name, image_sha256=metadata["sha256"],
                   metadata_sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest())
        with index.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        jpeg.unlink()
        jpeg.with_suffix(".jpg.json").unlink()
        refresh_library(self.root)
        check_library(self.root)
        self.assertFalse(png.exists())
        self.assertFalse(sidecar.exists())
        with Image.open(jpeg) as image:
            self.assertEqual((image.size, image.format, image.mode), ((500, 500), "JPEG", "RGB"))
        self.assertEqual(self.image.read_bytes(), original_before)

    def test_exact_library_copy_does_not_count_as_unapproved_image_reuse(self):
        Image.new("RGB", (500, 500), "white").save(self.image)
        self.assignment["image_sha256"] = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.write_assignments([self.assignment])
        refresh_library(self.root)
        library_image = self.root / "sources/image-library" / (self.items[0]["source_id"] + ".jpg")
        self.assertEqual(image_fingerprint(library_image), image_fingerprint(self.image))
        self.assertTrue(approved_library_pair({library_image.resolve(), self.image.resolve()}, self.root))
        unrelated = self.root / "data/unrelated.png"
        unrelated.write_bytes(self.image.read_bytes())
        self.assertFalse(approved_library_pair({library_image.resolve(), unrelated.resolve()}, self.root))
        self.assignment["visual_approval_status"] = "NOT_APPROVED"
        self.write_assignments([self.assignment])
        with self.assertRaisesRegex(ValueError, "stale"):
            check_library(self.root)

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
        self.assertEqual(workbook.sheetnames, ["Booklet"])
        sheet = workbook["Booklet"]
        self.assertEqual([sheet.cell(number, 1).value for number in range(4, 8)],
                         ["00042", "00042", "900042", "00043"])
        self.assertEqual(sheet["B7"].value, "=Unusual Product")
        self.assertEqual(sheet["B7"].data_type, "s")
        self.assertEqual(sheet["A4"].number_format, "@")
        self.assertEqual(sheet["A4"].data_type, "s")
        self.assertEqual(sheet.freeze_panes, "B4")
        self.assertEqual(sheet.auto_filter.ref, "A3:C7")
        self.assertEqual(sheet.page_setup.orientation, "landscape")
        self.assertEqual(str(sheet.page_setup.paperSize), sheet.PAPERSIZE_LETTER)
        self.assertIsNone(sheet["B2"].value)
        self.assertEqual(workbook.properties.identifier, "picklist-sha256:" + digest)
        self.assertEqual(len(sheet._images), 4)
        for index, picture in enumerate(sheet._images):
            self.assertEqual(picture.anchor._from.row, 3 + index)
            self.assertEqual(picture.anchor._from.col, 2)
            expected = display_image(self.image.read_bytes(), organic=index == 2)
            self.assertEqual(image_fingerprint(io.BytesIO(picture._data())),
                             image_fingerprint(io.BytesIO(expected)))
        self.assertEqual([cell.value for row in sheet.iter_rows() for cell in row if cell.value],
                         ["Fruit PLU Reference", "PLU", "Product", "Photo",
                          "00042", "Apple Gala", "00042", "Apple Gala",
                          "900042", "Organic Apple Gala", "00043", "=Unusual Product"])
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
                    workbook["Booklet"]["A4"] = 3283
                elif change == "formula":
                    workbook["Booklet"]["C4"] = "=1+1"
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
        self.assertEqual(workbook["Booklet"]["A4"].value, "03283")
        self.assertEqual(workbook.sheetnames, ["Booklet"])
        self.assertEqual(workbook["Booklet"]["C4"].value, None)
        self.assertEqual(len(workbook["Booklet"]._images), 0)
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
        self.write_source([("03283", "Honeycrisp Apple", True), ("903283", "Organic Honeycrisp Apple", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        first, second = [self.approved_assignment(item) for item in items]
        self.write_assignments([first, second])
        self.assertIn("PROHIBITED_IMAGE_REUSE", reconcile(self.root, self.output)[0][1]["blockers"])
        second["reuse_from_source_id"] = first["source_id"]
        self.write_assignments([first, second])
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_unrelated_organic_product_cannot_reuse_a_conventional_photo(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", True), ("903283", "Organic Banana", True),
        ])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        first, second = [self.approved_assignment(item) for item in items]
        second["reuse_from_source_id"] = first["source_id"]
        self.write_assignments([first, second])
        rows, _, _, summary = reconcile(self.root, self.output)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertTrue(all("PROHIBITED_IMAGE_REUSE" in row["blockers"] for row in rows))

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

    def test_owner_confirmed_permission_is_limited_to_approved_murcott_identity(self):
        repository = Path(__file__).resolve().parents[1]
        candidate = repository / "data/review-references/owner-alternates/4055-melissas.jpg"
        content = candidate.read_bytes()
        image_path = self.root / "data/murcott.jpg"
        image_path.write_bytes(content)
        item = dict(source_id="09df42d831061953e2d95b5f3e2071ef7f26a68b008377ecb6ce871b0b546186",
                    plu="4055", name="Murcott Tangerines")
        assignment = dict(
            image="data/murcott.jpg",
            image_sha256=hashlib.sha256(content).hexdigest(),
            reviewed_plu="4055", reviewed_product="Murcott Tangerines",
            rights_verification_status="OWNER_CONFIRMED_PERMISSION",
            production_status="APPROVED_FOR_EXACT_WORKINGLIST_ASSIGNMENT",
            photographic_origin="VERIFIED_PHOTO", visual_approval_status="APPROVED",
            provenance=dict(
                creator="Not identified in source", license="OWNER_CONFIRMED_PERMISSION",
                source_page_url="https://www.melissas.com/image.jpg",
                original_image_url="https://www.melissas.com/image.jpg",
                attribution="Owner-confirmed for this use", changes="Original image unchanged",
                rights_evidence="User confirmed permission for this exact image and use.",
            ),
        )
        self.assertEqual(reviewed_image(self.root, item, assignment)[3], [])
        item["name"] = "Clementines"
        errors = reviewed_image(self.root, item, assignment)[3]
        self.assertIn("IMAGE_RIGHTS_NOT_VERIFIED", errors)
        self.assertIn("SUPPORTED_IMAGE_LICENCE_REQUIRED", errors)
    def test_owner_confirmed_permission_requires_audit_evidence_not_a_public_licence(self):
        self.assignment["provenance"] = dict(
            creator="Not separately identified by the owner",
            license="OWNER_CONFIRMED_PERMISSION",
            rights_status="OWNER_CONFIRMED_PERMISSION",
            source_reference="Owner-uploaded image attachment",
            photographic_origin_evidence="Owner confirmed this is a photograph",
            visual_approval_evidence="Owner approved this image",
            attribution="Owner-provided image",
            changes="Original uploaded image bytes unchanged",
            rights_evidence="Owner confirmed permission for this repository",
        )
        self.assertEqual(reviewed_image(self.root, self.items[0], self.assignment)[3], [])
        self.assignment["provenance"]["license"] = "CC0"
        self.assertIn("OWNER_PERMISSION_MUST_NOT_CLAIM_PUBLIC_LICENCE",
                      reviewed_image(self.root, self.items[0], self.assignment)[3])

    def test_library_contains_only_approved_current_images_and_matches_booklet_output(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("42", "Unapproved", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        first = self.approved_assignment(items[0])
        second = self.approved_assignment(items[1])
        second["rights_verification_status"] = "NOT_VERIFIED"
        second["visual_approval_status"] = "REJECTED"
        # A distinct original ensures the approved entry is not blocked for sharing.
        other = self.root / "data/other.png"
        Image.new("RGB", (500, 600), "green").save(other)
        second.update(image="data/other.png", image_sha256=hashlib.sha256(other.read_bytes()).hexdigest())
        self.write_assignments([first, second])
        source_before, original_before = self.source.read_bytes(), self.image.read_bytes()
        library = self.root / "library"
        result = build_library(self.root, library)
        self.assertEqual((result["images"], result["catalogue_status"]), (1, "BLOCKED"))
        with (library / "IMAGE_LIBRARY.csv").open(encoding="utf-8-sig", newline="") as file:
            records = list(csv.DictReader(file))
        self.assertEqual([(r["plu"], r["product"]) for r in records], [("03283", "Honeycrisp Apple")])
        normalized = (library / records[0]["image"]).read_bytes()
        self.assertEqual(normalized, display_image(original_before))
        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.size, (500, 500))
            self.assertEqual((image.format, image.mode), ("JPEG", "RGB"))
            self.assertEqual(image.getpixel((250, 0)), (255, 255, 255))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in
                                zip(image.getpixel((250, 250)), (255, 0, 0))))
        metadata = json.loads((library / (records[0]["image"] + ".json")).read_text())
        self.assertEqual(metadata["original_image_sha256"], hashlib.sha256(original_before).hexdigest())
        self.assertEqual(metadata["working_source_ids"], [items[0]["source_id"]])
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(self.image.read_bytes(), original_before)
        with self.assertRaisesRegex(ValueError, "must be empty"):
            build_library(self.root, library)

    def test_library_retains_prior_visual_approvals_without_clearing_production_warnings(self):
        Image.new("RGB", (200, 150), "red").save(self.image)
        original = self.image.read_bytes()
        self.assignment.update(
            image_sha256=hashlib.sha256(original).hexdigest(),
            photographic_origin="NOT_VERIFIED", rights_verification_status="NOT_VERIFIED",
            provenance={})
        self.write_assignments([self.assignment])
        library = self.root / "sources/image-library"
        refresh_library(self.root)
        check_library(self.root)
        with (library / "IMAGE_LIBRARY.csv").open(encoding="utf-8-sig", newline="") as file:
            record = next(csv.DictReader(file))
        metadata = json.loads((library / (record["image"] + ".json")).read_text())
        self.assertEqual(metadata["photographic_origin"], "NOT_VERIFIED")
        self.assertEqual(record["rights_verification_status"], "NOT_VERIFIED")
        self.assertEqual(record["production_status"], "BLOCKED")
        for error in ("BELOW_500_PX", "IMAGE_RIGHTS_NOT_VERIFIED",
                      "PHOTOGRAPHIC_ORIGIN_NOT_VERIFIED"):
            self.assertIn(error, metadata["production_blockers"])
        self.assertNotIn("license", metadata)
        with Image.open(library / record["image"]) as image:
            self.assertEqual((image.size, image.format, image.mode), ((500, 500), "JPEG", "RGB"))
        self.assertEqual(self.image.read_bytes(), original)
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "BLOCKED")
        self.assignment["image_sha256"] = "stale"
        self.write_assignments([self.assignment])
        self.assertEqual(refresh_library(self.root)["images"], 0)

    def test_library_keeps_reuse_warnings_and_excludes_stale_product_reviews(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("42", "Other Apple", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        assignments = [self.approved_assignment(item) for item in items]
        self.write_assignments(assignments)
        refresh_library(self.root)
        with (self.root / "sources/image-library/IMAGE_LIBRARY.csv").open(
                encoding="utf-8-sig", newline="") as file:
            records = list(csv.DictReader(file))
        self.assertEqual(len(records), 2)
        self.assertTrue(all("PROHIBITED_IMAGE_REUSE" in r["production_blockers"] for r in records))
        assignments[1]["reviewed_product"] = "Previous identity"
        self.write_assignments(assignments)
        self.assertEqual(refresh_library(self.root)["images"], 1)

    def test_image_verifier_accepts_only_regenerated_legacy_library_copies(self):
        self.assignment.update(photographic_origin="NOT_VERIFIED",
                               rights_verification_status="NOT_VERIFIED", provenance={})
        self.write_assignments([self.assignment])
        refresh_library(self.root)
        library_image = (self.root / "sources/image-library" /
                         (self.items[0]["source_id"] + ".jpg"))
        command = [sys.executable, str(Path(__file__).with_name("verify_images.py").resolve()),
                   str(library_image)]
        verified = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("production limitations remain", verified.stdout)
        sidecar = library_image.with_suffix(".jpg.json")
        metadata = json.loads(sidecar.read_text())
        metadata["photographic_origin"] = "VERIFIED_PHOTO"
        sidecar.write_text(json.dumps(metadata))
        tampered = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(tampered.returncode, 0)
        self.assertIn("FAIL image library verification", tampered.stdout)

    def test_display_composites_transparency_on_white_without_stretching(self):
        original = io.BytesIO()
        Image.new("RGBA", (1000, 500), (255, 0, 0, 128)).save(original, format="PNG")
        with Image.open(io.BytesIO(display_image(original.getvalue()))) as image:
            self.assertEqual(image.size, (500, 500))
            self.assertEqual((image.format, image.mode), ("JPEG", "RGB"))
            self.assertEqual(image.getpixel((250, 0)), (255, 255, 255))
            self.assertTrue(all(abs(a - b) <= 2 for a, b in
                                zip(image.getpixel((250, 250)), (255, 127, 127))))

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
        metadata_path = self.image.with_suffix(".png.json")
        metadata = json.loads(metadata_path.read_text())
        metadata["changes"] = "Horizontally mirrored"
        metadata_path.write_text(json.dumps(metadata))
        rebuild_working_list(self.root, self.root / "audit")
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
        self.assertEqual(entry["provenance"]["changes"], "Horizontally mirrored")
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

        library = self.root / "sources/image-library"
        with (library / "IMAGE_LIBRARY.csv").open(encoding="utf-8-sig", newline="") as file:
            records = list(csv.DictReader(file))
        self.assertEqual([row["source_id"] for row in records], [self.items[0]["source_id"]])
        self.assertEqual((library / records[0]["image"]).read_bytes(), display_image(image.read_bytes()))
        Image.new("RGB", (600, 500), "blue").save(self.image)
        self.candidate_metadata()
        approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                digest, "Reviewed replacement and licence", replace=True)
        check_library(self.root)
        with Image.open(library / records[0]["image"]) as updated:
            self.assertTrue(all(abs(a - b) <= 2 for a, b in
                                zip(updated.getpixel((250, 250)), (0, 0, 255))))
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_explicit_organic_reuse_keeps_separate_product_sidecars(self):
        self.write_source([("03283", "Honeycrisp Apple", True),
                           ("93283", "Organic Honeycrisp Apple", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        self.write_assignments([])
        rebuild_working_list(self.root, self.output)
        self.candidate_metadata()
        approve(self.root, items[0]["source_id"], self.image, "Fruit", "Apples",
                self.digest, "Reviewed photo and rights")
        metadata_path = self.image.with_suffix(".png.json")
        metadata = json.loads(metadata_path.read_text())
        metadata.update(plu="93283", product="Organic Honeycrisp Apple")
        metadata_path.write_text(json.dumps(metadata))
        approve(self.root, items[1]["source_id"], self.image, "Fruit", "Apples",
                self.digest, "Reviewed organic reuse and rights", reuse_from=items[0]["source_id"])
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        conventional = self.root / assignments[items[0]["source_id"]]["image"]
        organic = self.root / assignments[items[1]["source_id"]]["image"]
        self.assertNotEqual(conventional, organic)
        self.assertEqual(conventional.read_bytes(), organic.read_bytes())
        self.assertEqual(json.loads(conventional.with_suffix(".png.json").read_text())["product"],
                         "Honeycrisp Apple")
        self.assertEqual(json.loads(organic.with_suffix(".png.json").read_text())["product"],
                         "Organic Honeycrisp Apple")
        rows, _, _, _ = reconcile(self.root, self.output)
        self.assertTrue(all("PROHIBITED_IMAGE_REUSE" not in row["blockers"] for row in rows))
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_approval_rejects_reuse_for_a_different_product(self):
        self.write_source([
            ("03283", "Honeycrisp Apple", True), ("903283", "Organic Banana", True),
        ])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        self.write_assignments([self.approved_assignment(items[0])])
        rebuild_working_list(self.root, self.output)
        self.candidate_metadata()
        metadata_path = self.image.with_suffix(".png.json")
        metadata = json.loads(metadata_path.read_text())
        metadata.update(plu=items[1]["plu"], product=items[1]["name"])
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "same product"):
            approve(self.root, items[1]["source_id"], self.image, "Fruit", "Apples",
                    self.digest, "Reviewed photo and rights", reuse_from=items[0]["source_id"])
        self.assertNotIn(items[1]["source_id"], read_assignments(
            self.root / "data/picklist_assignments.json"))

    def test_owner_permission_approval_preserves_permission_without_public_licence(self):
        evidence = 'User attestation: "I own this image and all the rights to it so I approve it completely"'
        metadata = dict(
            plu=self.items[0]["plu"], product=self.items[0]["name"],
            creator="Not separately identified by the owner",
            license="OWNER_CONFIRMED_PERMISSION",
            rights_status="OWNER_CONFIRMED_PERMISSION",
            source_reference="Owner-uploaded image attachment",
            rights_evidence=evidence,
            photographic_origin="OWNER_CONFIRMED_PHOTO",
            photographic_origin_evidence="User confirmed this is an actual photograph",
            visual_approval_evidence=evidence,
            attribution="Owner-provided image; no separate public attribution supplied",
            width=600, height=500,
            sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
            approval_status="CANDIDATE",
        )
        self.image.with_suffix(".png.json").write_text(json.dumps(metadata))
        rebuild_working_list(self.root, self.root / "audit")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                digest, evidence, replace=True)
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        entry = assignments[self.items[0]["source_id"]]
        self.assertEqual(entry["rights_verification_status"], "VERIFIED")
        self.assertEqual(entry["provenance"]["rights_status"], "OWNER_CONFIRMED_PERMISSION")
        self.assertEqual(entry["provenance"]["license"], "OWNER_CONFIRMED_PERMISSION")
        self.assertFalse(entry["provenance"]["license_url"])
        approved_sidecar = json.loads(
            (self.root / entry["image"]).with_suffix(".png.json").read_text())
        self.assertEqual(approved_sidecar["visual_approval_status"], "APPROVED")
        self.assertEqual(approved_sidecar["rights_verification_status"], "VERIFIED")
        self.assertTrue(approved_sidecar["visual_approval_evidence"])
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")

    def test_approval_still_reports_production_blockers_after_library_inclusion(self):
        self.write_source([("03283", "Honeycrisp Apple", True), ("42", "Other Apple", True)])
        items, _ = read_picklist(self.source)
        self.register_current_source(items)
        self.write_assignments([self.approved_assignment(item) for item in items])
        self.candidate_metadata()
        rebuild_working_list(self.root, self.root / "audit")
        with self.assertRaisesRegex(ValueError, "remains blocked for production.*PROHIBITED_IMAGE_REUSE"):
            approve(self.root, items[0]["source_id"], self.image, "Fruit", "Apples",
                    self.digest, "Test licence evidence", replace=True)
        self.assertIn(items[0]["source_id"], check_library(self.root)["blockers_by_source_id"])

    def test_approval_reports_library_refresh_failure_without_overwriting_edits(self):
        self.candidate_metadata()
        rebuild_working_list(self.root, self.root / "audit")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        refresh_library(self.root)
        library_image = self.root / "sources/image-library" / (self.items[0]["source_id"] + ".jpg")
        library_image.write_bytes(b"manual edit")
        with self.assertRaisesRegex(ValueError, "approval was saved, but library refresh failed"):
            approve(self.root, self.items[0]["source_id"], self.image, "Fruit", "Apples",
                    digest, "Reviewed photo and rights", replace=True)
        self.assertEqual(library_image.read_bytes(), b"manual edit")
        entry = read_assignments(self.root / "data/picklist_assignments.json")[self.items[0]["source_id"]]
        self.assertEqual(entry["provenance"]["rights_evidence"], "Reviewed photo and rights")

    def test_changed_working_identity_can_receive_a_fresh_image_approval(self):
        source_item = self.items[0]
        self.write_registry(self.items, decisions=[dict(
            plu=source_item["plu"], canonical_name="Reviewed Working Apple", mode="MERGE",
            source_ids=[source_item["source_id"]],
            selected_source_ids=[source_item["source_id"]],
            condition="Owner-approved display name")])
        rebuild_working_list(self.root, self.root / "audit")
        working, digest = read_working_list(self.root)
        item = working[0]
        self.assertTrue(item["identity_changed"])
        self.candidate_metadata()
        metadata_path = self.image.with_suffix(".png.json")
        metadata = json.loads(metadata_path.read_text())
        metadata["product"] = item["name"]
        metadata_path.write_text(json.dumps(metadata))
        source_before = self.source.read_bytes()
        approve(self.root, item["source_id"], self.image, "Fruit", "Apples",
                digest, "Reviewed exact product source and rights", replace=True)
        assignments = read_assignments(self.root / "data/picklist_assignments.json")
        self.assertEqual(assignments[item["source_id"]]["working_source_ids"],
                         [source_item["source_id"]])
        self.assertEqual(reconcile(self.root, self.output)[3]["status"], "READY_TO_BUILD")
        self.assertEqual(self.source.read_bytes(), source_before)

    def test_approval_rejects_stale_xml_wrong_products_and_unrequested_replacements(self):
        self.candidate_metadata()
        rebuild_working_list(self.root, self.root / "audit")
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
