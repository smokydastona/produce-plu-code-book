import csv
import tempfile
import unittest
from pathlib import Path

from license_register import register_row, write_register
from verify_images import LICENSES


class LicenseRegisterTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "idx": "009", "plu": "03283", "product": "Honeycrisp apple",
            "image": "originals/009/1/03283.jpg", "creator": "Photographer",
            "license": "CC BY-SA 2.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/2.0/",
            "source_page_url": "https://commons.wikimedia.org/wiki/File:Apple.jpg",
            "original_image_url": "https://upload.wikimedia.org/Apple.jpg",
            "commons_metadata": {"extmetadata": {
                "Attribution": {"value": "<b>Required credit</b>"},
                "Permission": {"value": "Retain &amp; credit"},
            }},
        }

    def test_share_alike_and_required_credit(self):
        row = register_row(self.record)
        self.assertEqual(row["license_eligibility"], "ACCEPTED_TYPE")
        self.assertEqual(row["license_version"], "2.0")
        self.assertEqual(row["share_alike"], "ADAPTATIONS_ONLY")
        self.assertEqual(row["attribution_required"], "YES")
        self.assertIn("Required credit", row["attribution"])
        self.assertIn(self.record["source_page_url"], row["attribution"])
        self.assertIn(self.record["license_url"], row["attribution"])
        self.assertEqual(row["permission_notes"], "Retain & credit")

    def test_each_type_stays_unverified(self):
        for name in LICENSES:
            with self.subTest(license=name):
                self.record.update(license=name, approval_status="APPROVED")
                row = register_row(self.record)
                self.assertEqual(row["rights_verification_status"], "NOT_VERIFIED")
                self.assertEqual(row["visual_approval_status"], "NOT_APPROVED")
                if name == "Public domain":
                    self.assertEqual(row["license_eligibility"], "CONDITIONAL_PUBLIC_DOMAIN")
                    self.assertEqual(row["commercial_use"], "UNVERIFIED")
                else:
                    self.assertEqual(row["license_eligibility"], "ACCEPTED_TYPE")
                    self.assertEqual(row["commercial_use"], "PERMITTED_IF_DECLARATION_VALID")

    def test_non_share_alike_and_cc0(self):
        for name in ("CC BY 2.0", "CC BY 3.0", "CC BY 4.0", "CC0"):
            self.record["license"] = name
            row = register_row(self.record)
            self.assertEqual(row["share_alike"], "NO")
            self.assertEqual(row["attribution_required"],
                             "NO_COPYRIGHT_REQUIREMENT" if name == "CC0" else "YES")

    def test_unknown_and_restricted_claims_not_eligible(self):
        self.record["license"] = "CC BY-NC 4.0"
        self.assertEqual(register_row(self.record)["license_eligibility"], "REQUIRES_REVIEW")
        self.record["license"] = "CC BY-SA 4.0"
        self.record["commons_metadata"]["extmetadata"]["Restrictions"] = {"value": "Other rights"}
        row = register_row(self.record)
        self.assertEqual(row["license_eligibility"], "REQUIRES_REVIEW")
        self.assertEqual(row["commercial_use"], "UNVERIFIED")

    def test_associations_preserved_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "register.csv"
            write_register([self.record, dict(self.record, idx="274")], path)
            with path.open(newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual([r["idx"] for r in rows], ["009", "274"])
            self.assertEqual([r["plu"] for r in rows], ["03283", "03283"])
            with self.assertRaises(FileExistsError):
                write_register([self.record], path)

    def test_missing_source_fails_before_writing(self):
        del self.record["source_page_url"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "register.csv"
            with self.assertRaises(ValueError):
                write_register([self.record], path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
