import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import retrieve_commons
from verify_images import validate


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
                retrieve_commons.download("3283", "Honeycrisp apple", output, "test")
            page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = "CC BY-SA 4.0"
            self.assertFalse(retrieve_commons.download("4555", "Savoy cabbage", output, "test"))
            self.assertTrue(retrieve_commons.download(
                "4555", "Savoy cabbage", output, "test", licenses=retrieve_commons.LICENSES))

    def test_all_rejected_entries_have_exact_queries(self):
        root = Path(__file__).resolve().parents[1]
        entries = retrieve_commons.rejected_entries(root / "data/image_review.csv")
        self.assertEqual(len(entries), 31)
        self.assertEqual(len({entry["idx"] for entry in entries}), 31)
        self.assertEqual({entry["idx"] for entry in entries}, set(retrieve_commons.QUERIES))

    def test_package_partial_errors_and_duplicate_plus_organic_entries(self):
        entries = [
            {"idx": "27", "plu": "3016", "name": "Pear Concorde"},
            {"idx": "274", "plu": "93016", "name": "Organic Pear Concord"},
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
        self.assertEqual(records[0]["approval_status"], "CANDIDATE")
        self.assertEqual(records[0]["license"], "CC BY 4.0")
        self.assertEqual((output / records[0]["image"]).read_bytes(), content)
        self.assertTrue((output / "contact-sheet-01.jpg").is_file())
        import csv
        with (output / "acquisition-report.csv").open() as file:
            report = list(csv.DictReader(file))
        self.assertEqual([r["status"] for r in report], ["CANDIDATES_ONLY", "UNRESOLVED", "ERROR"])
        with self.assertRaises(ValueError):
            retrieve_commons.acquire(entries, output, "test", 2)


if __name__ == "__main__":
    unittest.main()
