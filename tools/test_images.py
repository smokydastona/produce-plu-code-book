import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image, ImageOps

import retrieve_commons
import verify_images
from check_image_uniqueness import audit_entries, image_fingerprint, require_unique_entries
from verify_images import LICENSES, validate
from organic_watermarks import badge_artwork, is_organic, render_watermark, verified_original, VERSION


class ImageChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "3283.jpg"
        Image.new("RGB", (600, 500)).save(self.path)
        self.record = {
            "plu": "3283", "product": "Honeycrisp apple", "creator": "Photographer",
            "license": "CC0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "source_page_url": "https://commons.wikimedia.org/wiki/File:Apple.jpg",
            "original_image_url": "https://upload.wikimedia.org/Apple.jpg",
            "width": 600, "height": 500, "attribution": "Photographer / CC0",
            "approval_status": "CANDIDATE",
        }
        self.write_record()

    def write_record(self):
        self.path.with_suffix(".jpg.json").write_text(json.dumps(self.record))

    def test_exact_minimum_passes(self):
        self.assertEqual(validate(self.path), [])

    def test_all_accepted_licence_types(self):
        for name in LICENSES:
            with self.subTest(license=name):
                self.record["license"] = name
                self.write_record()
                self.assertEqual(validate(self.path), [])

    def test_owner_permission_is_exact_asset_and_working_identity_only(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4055-melissas.jpg"
        metadata = json.loads(candidate.with_suffix(".jpg.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field, value in (
                ("sha256", "different"), ("plu", "4056"),
                ("product", "Clementines"), ("working_list_id", "different"),
                ("license", "CC0"), ("rights_verification_status", "VERIFIED"),
                ("photographic_origin", "UNVERIFIED"),
                ("visual_approval_status", "CANDIDATE")):
            with self.subTest(field=field):
                altered = dict(metadata, **{field: value})
                self.assertFalse(verify_images.owner_permission_metadata(altered))

    def test_owner_permission_for_napa_does_not_transfer_to_another_product(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4552-foxy.png"
        metadata = json.loads(candidate.with_suffix(".png.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_permission_for_strawberries_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4253-strawberries.jpg"
        metadata = json.loads(candidate.with_suffix(".jpg.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_approved_basil_is_exact_mirror_for_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4885-mirrored.png"
        original = root / "data/review-references/owner-alternates/4885-original.jpg"
        metadata = json.loads(candidate.with_suffix(".png.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        with Image.open(original) as source, Image.open(candidate) as mirrored:
            self.assertEqual(ImageOps.mirror(ImageOps.exif_transpose(source)).convert("RGBA").tobytes(),
                             mirrored.convert("RGBA").tobytes())
        self.assertFalse(verify_images.owner_permission_metadata(
            dict(metadata, working_list_id="different")))

    def test_owner_permission_for_cilantro_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4889-cilantro.jpg"
        metadata = json.loads(candidate.with_suffix(".jpg.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_permission_for_tangerine_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4458-tangerine.jpg"
        metadata = json.loads(candidate.with_suffix(".jpg.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_permission_for_white_creamer_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4724-white-creamer.png"
        metadata = json.loads(candidate.with_suffix(".png.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_permission_for_red_creamer_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4723-red-creamer.jpg"
        metadata = json.loads(candidate.with_suffix(".jpg.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_owner_permission_for_sweet_potato_is_exact_identity(self):
        root = Path(__file__).resolve().parents[1]
        candidate = root / "data/review-references/owner-alternates/4074-sweet-potato.png"
        metadata = json.loads(candidate.with_suffix(".png.json").read_text())
        self.assertEqual(validate(candidate), [])
        self.assertTrue(verify_images.owner_permission_metadata(metadata))
        for field in ("sha256", "plu", "product", "working_list_id"):
            with self.subTest(field=field):
                self.assertFalse(verify_images.owner_permission_metadata(
                    dict(metadata, **{field: "different"})))

    def test_shortest_side_not_longest(self):
        Image.new("RGB", (1000, 499)).save(self.path)
        self.assertTrue(any("minimum is 500" in e for e in validate(self.path)))

    def test_missing_and_invalid_metadata(self):
        self.path.with_suffix(".jpg.json").unlink()
        self.assertTrue(validate(self.path))
        self.path.with_suffix(".jpg.json").write_text("[]")
        self.assertTrue(validate(self.path))

    def test_invalid_claims(self):
        self.record.update(license="All rights reserved", creator="",
                           width=999, approval_status="APPROVED",
                           source_page_url="not a URL")
        self.write_record()
        self.assertGreaterEqual(len(validate(self.path)), 5)

    def test_corrupt_image(self):
        self.path.write_bytes(b"not an image")
        self.assertTrue(validate(self.path))

    def test_candidate_download_and_no_overwrite(self):
        page = {
            "title": "File:Honeycrisp.jpg", "imageinfo": [{
                "width": 600, "height": 500, "mime": "image/jpeg",
                "url": self.record["original_image_url"],
                "descriptionurl": self.record["source_page_url"],
                "extmetadata": {
                    "Artist": {"value": "<b>Photographer</b>"},
                    "LicenseShortName": {"value": "CC0"},
                    "LicenseUrl": {"value": self.record["license_url"]},
                },
            }],
        }
        content = io.BytesIO()
        Image.new("RGB", (600, 500)).save(content, format="JPEG")
        output = self.root / "downloads"
        with patch.object(retrieve_commons, "search", return_value=[page]), \
                patch.object(retrieve_commons, "fetch", return_value=content.getvalue()):
            self.assertTrue(retrieve_commons.download("3283", "Honeycrisp apple", output, "test"))
            self.assertEqual(validate(output / "3283.jpg"), [])
            with self.assertRaises(FileExistsError):
                with patch.object(retrieve_commons, "fetch", return_value=self.different_image()):
                    retrieve_commons.download("3283", "Honeycrisp apple", output, "test")
            self.assertFalse(retrieve_commons.download("4555", "Savoy cabbage", output, "test"))
            self.assertFalse((output / "4555.jpg").exists())
            page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = "CC BY-SA 4.0"
            with patch.object(retrieve_commons, "fetch", return_value=self.different_image()):
                self.assertTrue(retrieve_commons.download(
                    "4555", "Savoy cabbage", output, "test"))
            page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = "CC BY-NC 4.0"
            self.assertFalse(retrieve_commons.download("9999", "Unsupported", output, "test"))

    def test_all_rejected_entries_have_exact_queries(self):
        root = Path(__file__).resolve().parents[1]
        entries = retrieve_commons.rejected_entries(root / "data/image_review.csv")
        self.assertEqual(len(entries), 31)
        self.assertEqual(len({entry["idx"] for entry in entries}), 31)
        self.assertEqual({entry["idx"] for entry in entries}, set(retrieve_commons.QUERIES))

    def test_all_entry_queries_keep_variety_and_drop_only_label_or_size(self):
        query = retrieve_commons.entry_query(
            {"idx": "999", "name": "Organic Apples Golden Delicious Large"})
        self.assertEqual(query, "apple Golden Delicious")
        self.assertEqual(retrieve_commons.entry_query(
            {"idx": "50", "name": "Grapefruit White Large"}), "white grapefruit")
        with self.assertRaisesRegex(ValueError, "empty product"):
            retrieve_commons.entry_query({"idx": "999", "name": "Organic"})
        self.assertEqual(retrieve_commons.entry_query(
            {"idx": "50", "name": "New product after XML reorder", "query": "specific new variety"}),
            "specific new variety")
        self.assertEqual(retrieve_commons.entry_query(
            {"idx": "50", "source_id": "new-identity", "name": "New apple"}),
            "New apple")

    def test_all_entry_selection_shards_cover_every_entry_once(self):
        root = Path(__file__).resolve().parents[1]
        import csv
        with (root / "data/image_review.csv").open(encoding="utf-8-sig") as file:
            entries = list(csv.DictReader(file))
        groups = [entries[index::6] for index in range(6)]
        ids = [row["idx"] for group in groups for row in group]
        self.assertEqual(len(ids), len(entries))
        self.assertEqual(len(set(ids)), len(entries))
        self.assertTrue(all(retrieve_commons.entry_query(row) for row in entries))

    def test_package_partial_errors_and_duplicate_plus_organic_entries(self):
        entries = [
            {"idx": "27", "plu": "3016", "name": "Pear Concorde"},
            {"idx": "274", "plu": "93016", "name": "Organic Pear Concord"},
            {"idx": "344", "plu": "4565", "name": "Carrot - Red"},
            {"idx": "9", "plu": "3283", "name": "Apples Honey Crisp"},
        ]
        page = {
            "title": "File:Concorde.jpg", "imageinfo": [{
                "width": 600, "height": 500, "mime": "image/jpeg",
                "url": self.record["original_image_url"],
                "descriptionurl": self.record["source_page_url"],
                "extmetadata": {
                    "Artist": {"value": "Photographer"},
                    "LicenseShortName": {"value": "CC BY 4.0"},
                    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                },
            }],
        }
        content = self.path.read_bytes()
        output = self.root / "package"
        with patch.object(retrieve_commons, "search", side_effect=[[page], [], OSError("network failure")]), \
                patch.object(retrieve_commons, "fetch", return_value=content):
            self.assertTrue(retrieve_commons.acquire(entries, output, "test", 2))
        records = json.loads((output / "provenance.json").read_text())
        self.assertEqual(len(records), 1)
        self.assertEqual([r["idx"] for r in records], ["27"])
        self.assertEqual(records[0]["approval_status"], "CANDIDATE")
        self.assertEqual(records[0]["license"], "CC BY 4.0")
        self.assertEqual((output / records[0]["image"]).read_bytes(), content)
        self.assertTrue((output / "contact-sheet-01.jpg").is_file())
        import csv
        with (output / "license-register.csv").open() as file:
            licences = list(csv.DictReader(file))
        self.assertEqual([r["idx"] for r in licences], ["27"])
        self.assertTrue(all(r["rights_verification_status"] == "NOT_VERIFIED" for r in licences))
        self.assertTrue(all(r["visual_approval_status"] == "NOT_APPROVED" for r in licences))
        with (output / "acquisition-report.csv").open() as file:
            report = list(csv.DictReader(file))
        self.assertEqual([r["status"] for r in report],
                         ["CANDIDATES_ONLY", "UNRESOLVED", "UNRESOLVED", "ERROR"])
        with self.assertRaises(ValueError):
            retrieve_commons.acquire(entries, output, "test", 2)

    def test_rate_limit_retries_and_pacing(self):
        response = io.BytesIO(b"image")
        error = HTTPError("https://commons.wikimedia.org/", 429, "rate limit",
                          {"Retry-After": "15"}, None)
        with patch.object(retrieve_commons, "urlopen", side_effect=[error, response]) as request, \
                patch.object(retrieve_commons.time, "sleep") as sleep:
            self.assertEqual(retrieve_commons.fetch("https://commons.wikimedia.org/", "test"), b"image")
            self.assertEqual(request.call_count, 2)
            self.assertIn(unittest.mock.call(15), sleep.call_args_list)

    def test_xml_requests_do_not_inherit_legacy_index_leads(self):
        entries = [{"idx": "50", "source_id": "new-identity", "plu": "00042",
                    "name": "New Apple"}]
        leads = [{"id": "50", "source_page_url": "https://commons.wikimedia.org/wiki/File:Old.jpg"}]
        with patch.object(retrieve_commons, "search", return_value=[]) as search:
            self.assertFalse(retrieve_commons.acquire(entries, self.root / "package", "test", 1, leads))
        search.assert_called_once_with("New Apple", "test")

    def different_image(self):
        content = io.BytesIO()
        Image.new("RGB", (600, 500), "red").save(content, format="JPEG")
        return content.getvalue()

    def test_pixel_duplicates_ignore_filename_format_and_metadata(self):
        other = self.root / "different-name.png"
        with Image.open(self.path) as image:
            image.save(other, comment="different metadata")
        self.assertEqual(image_fingerprint(self.path), image_fingerprint(other))
        other.write_bytes(self.different_image())
        self.assertNotEqual(image_fingerprint(self.path), image_fingerprint(other))

    def test_entry_uniqueness_includes_repeated_plus_and_cross_book_reuse(self):
        other = self.root / "copy.jpg"
        other.write_bytes(self.path.read_bytes())
        rows = [
            {"idx": "1", "plu": "03283", "book": "Fruit", "image": self.path.name},
            {"idx": "2", "plu": "03283", "book": "Vegetable", "image": other.name},
        ]
        self.assertEqual(audit_entries(rows, self.root), [rows])
        with self.assertRaisesRegex(ValueError, "2 entries share images"):
            require_unique_entries(rows, self.root)
        rows[1]["plu"] = "9999"
        self.assertEqual(audit_entries(rows, self.root), [rows])
        other.write_bytes(self.different_image())
        self.assertEqual(audit_entries(rows, self.root), [])
        require_unique_entries(rows, self.root)
        rows[1]["image"] = ""
        with self.assertRaisesRegex(ValueError, "missing image"):
            audit_entries(rows, self.root)
        rows[1]["idx"] = "1"
        with self.assertRaisesRegex(ValueError, "repeated entry ID"):
            audit_entries(rows, self.root)

    def test_cli_rejects_changed_duplicate_but_not_legacy_duplicates(self):
        first = self.root / "one.jpg"
        second = self.root / "two.jpg"
        third = self.root / "three.jpg"
        for path in (first, second):
            path.write_bytes(self.path.read_bytes())
        third.write_bytes(self.different_image())
        for changed, expected in ((second, 1), (third, 0)):
            with self.subTest(changed=changed), \
                    patch("sys.argv", ["verify_images", str(changed)]), \
                    patch.object(verify_images, "validate", return_value=[]), \
                    patch.object(verify_images, "Path", side_effect=lambda value:
                                 self.root if value in ("data/images", "sources") else Path(value)):
                with self.assertRaises(SystemExit) as result:
                    verify_images.main()
                self.assertEqual(result.exception.code, expected)

    def test_acquisition_tries_next_candidate_after_duplicate(self):
        page = {
            "title": "File:First.jpg", "imageinfo": [{
                "width": 600, "height": 500, "mime": "image/jpeg",
                "url": self.record["original_image_url"],
                "descriptionurl": self.record["source_page_url"],
                "extmetadata": {
                    "Artist": {"value": "Photographer"},
                    "LicenseShortName": {"value": "CC0"},
                    "LicenseUrl": {"value": self.record["license_url"]},
                },
            }],
        }
        entries = [
            {"idx": "361", "plu": "4724", "name": "White creamer potato"},
            {"idx": "368", "plu": "4724", "name": "White creamer potato"},
        ]
        other = dict(page, title="File:Second.jpg")
        output = self.root / "package"
        with patch.object(retrieve_commons, "search", return_value=[page, other]), \
                patch.object(retrieve_commons, "fetch", side_effect=[
                    self.path.read_bytes(), self.path.read_bytes(), self.different_image(),
                ]):
            self.assertFalse(retrieve_commons.acquire(entries, output, "test", 1))
        records = json.loads((output / "provenance.json").read_text())
        self.assertEqual([row["idx"] for row in records], ["361", "368"])
        self.assertNotEqual(
            image_fingerprint(output / records[0]["image"]),
            image_fingerprint(output / records[1]["image"]),
        )

    def test_acquisition_records_unsafe_images_and_tries_later_candidates(self):
        import csv

        page = {
            "title": "File:Advertised-large.jpg", "imageinfo": [{
                "width": 900, "height": 900, "mime": "image/jpeg",
                "url": self.record["original_image_url"],
                "descriptionurl": self.record["source_page_url"],
                "extmetadata": {
                    "Artist": {"value": "Photographer"},
                    "LicenseShortName": {"value": "CC0"},
                    "LicenseUrl": {"value": self.record["license_url"]},
                },
            }],
        }
        pages = [page]
        for title in ("Warning", "Error", "Corrupt", "Valid"):
            pages.append({
                "title": f"File:{title}.jpg",
                "imageinfo": [dict(page["imageinfo"][0], width=600, height=500)],
            })
        def encoded(size):
            image = io.BytesIO()
            Image.new("RGB", size).save(image, format="JPEG")
            return image.getvalue()

        output = self.root / "package"
        entries = [{"idx": "999", "plu": "3283", "name": "Honeycrisp apple"}]
        with patch.object(Image, "MAX_IMAGE_PIXELS", 300000), \
                patch.object(retrieve_commons, "search", return_value=pages), \
                patch.object(retrieve_commons, "fetch", side_effect=[
                    encoded((650, 500)), encoded((800, 800)), b"not an image",
                    self.path.read_bytes(),
                ]) as fetch:
            self.assertFalse(retrieve_commons.acquire(entries, output, "test", 1))
        self.assertEqual(fetch.call_count, 4)
        records = json.loads((output / "provenance.json").read_text())
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["approval_status"], "CANDIDATE")
        with (output / "acquisition-report.csv").open() as file:
            report = list(csv.DictReader(file))
        self.assertEqual(report[0]["status"], "CANDIDATES_ONLY")
        for title in ("Advertised-large", "Warning", "Error", "Corrupt"):
            self.assertIn(f"File:{title}.jpg", report[0]["details"])
        self.assertTrue((output / "contact-sheet-01.jpg").is_file())
        self.assertTrue((output / "license-register.csv").is_file())


class OrganicWatermarkChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "conventional.jpg").write_bytes(self.image_bytes("green"))
        self.content = (self.data / "conventional.jpg").read_bytes()
        (self.data / "organic.png").write_bytes(render_watermark(self.content))
        source = self.root / "sources/visual/FRUIT_VISUAL_PLU_BOOKLET_CORRECTED.docx"
        source.parent.mkdir(parents=True)
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("word/media/image1.jpg", self.content)
        self.rows = [
            {"idx": "1", "book": "Fruit", "plu": "4011", "name": "Banana",
             "image": "conventional.jpg"},
            {"idx": "2", "book": "Fruit", "plu": "94011", "name": "Organic Banana",
             "image": "organic.png"},
        ]
        import hashlib
        self.record = dict(self.rows[1], watermark=VERSION,
                           source_document=str(source.relative_to(self.root)),
                           source_member="word/media/image1.jpg",
                           original_sha256=hashlib.sha256(self.content).hexdigest(),
                           badge_sha256=hashlib.sha256(badge_artwork()).hexdigest())
        self.write_manifest()

    def image_bytes(self, color):
        content = io.BytesIO()
        Image.new("RGB", (600, 500), color).save(content, format="JPEG")
        return content.getvalue()

    def write_manifest(self):
        (self.data / "organic_watermarks.json").write_text(json.dumps([self.record]))

    def test_all_organic_identifiers_are_recognized(self):
        for row in ({"name": "Buddha's Hand Organic", "plu": "2159"},
                    {"section": "Organic Fruit"}, {"category": "Organic Apple"}):
            self.assertTrue(is_organic(row))
        self.assertFalse(is_organic({"name": "Banana", "plu": "94011"}))

    def test_watermark_is_standard_pink_and_preserves_dimensions(self):
        with Image.open(io.BytesIO(render_watermark(self.content))) as image:
            self.assertEqual(image.size, (600, 500))
            with Image.open(io.BytesIO(self.content)) as original:
                top_left = image.crop((0, 0, 180, 180)).getcolors(180 * 180)
                self.assertGreater(sum(count for count, (r, g, b) in top_left
                                       if r > 200 and b > 100 and g < 120), 0)
                self.assertEqual(image.crop((200, 200, 600, 500)).tobytes(),
                                 original.crop((200, 200, 600, 500)).tobytes())
                self.assertNotEqual(image.crop((0, 0, 200, 200)).tobytes(),
                                    original.crop((0, 0, 200, 200)).tobytes())
        self.assertEqual(verified_original(self.rows[1], self.record, self.data), self.content)

    def test_matching_pair_is_allowed_only_with_verified_watermark(self):
        self.assertEqual(audit_entries(self.rows, self.data), [])
        (self.data / "organic.png").write_bytes(self.content)
        with self.assertRaisesRegex(ValueError, "missing or altered"):
            audit_entries(self.rows, self.data)

    def test_missing_watermark_record_is_rejected(self):
        (self.data / "organic_watermarks.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing pink"):
            audit_entries(self.rows, self.data)

    def test_badge_checksum_is_required(self):
        self.record["badge_sha256"] = "bad"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "badge checksum mismatch"):
            audit_entries(self.rows, self.data)

    def test_badge_migration_still_verifies_image_pixels(self):
        self.record["watermark"] = "PINK_ORGANIC_BADGE_TOP_LEFT_V2"
        self.record.pop("badge_sha256")
        self.assertEqual(verified_original(
            self.rows[1], self.record, self.data, allow_legacy=True), self.content)
        (self.data / "organic.png").write_bytes(self.content)
        with self.assertRaisesRegex(ValueError, "missing or altered"):
            verified_original(self.rows[1], self.record, self.data, allow_legacy=True)

    def test_organic_reuse_of_unrelated_conventional_product_is_rejected(self):
        self.rows[1]["plu"] = self.record["plu"] = "94012"
        self.write_manifest()
        self.assertEqual(audit_entries(self.rows, self.data), [self.rows])

    def test_repeated_conventional_plus_remain_prohibited(self):
        duplicate = dict(self.rows[0], idx="3")
        self.assertEqual(audit_entries(self.rows + [duplicate], self.data),
                         [[self.rows[0], self.rows[1], duplicate]])

    def test_watermark_cannot_hide_organic_only_duplicates(self):
        duplicate = dict(self.rows[1], idx="3")
        (self.data / "organic_watermarks.json").write_text(
            json.dumps([self.record, dict(self.record, idx="3")]))
        self.assertEqual(audit_entries([self.rows[1], duplicate], self.data),
                         [[self.rows[1], duplicate]])

    def test_tampered_original_or_record_is_rejected(self):
        self.record["original_sha256"] = "bad"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            audit_entries(self.rows, self.data)
        self.record["image"] = "wrong.png"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "record image mismatch"):
            audit_entries(self.rows, self.data)

    def test_legacy_reuse_baseline_does_not_require_a_new_watermark(self):
        self.rows[1]["image"] = self.rows[0]["image"]
        self.assertEqual(audit_entries(self.rows, self.data, check_watermarks=False), [])


if __name__ == "__main__":
    unittest.main()
