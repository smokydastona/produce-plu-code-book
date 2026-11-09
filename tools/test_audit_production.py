import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from audit_production import image_blockers, inventory


class ProductionAuditChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        self.image = self.root / "data/apple.png"
        Image.new("RGB", (500, 500), "red").save(self.image)
        self.row = dict(idx="1", book="Fruit", plu="03283", name="Apple",
                        image="apple.png", width="500", height="500", source="Photo")
        self.review = dict(self.row, verdict="Approved")

    def test_existing_unverified_image_is_never_release_ready(self):
        _, _, errors = image_blockers(self.row, self.review, self.root)
        self.assertIn("MISSING_IMAGE_PROVENANCE_AND_RIGHTS_VERIFICATION", errors)

    def test_reports_resolution_ai_and_visual_problems_separately(self):
        Image.new("RGB", (1000, 499)).save(self.image)
        self.row["source"] = "AI Generated"
        self.review["verdict"] = "Rejected"
        width, height, errors = image_blockers(self.row, self.review, self.root)
        self.assertEqual((width, height), (1000, 499))
        for error in ("BELOW_500_PX", "RECORDED_DIMENSIONS_MISMATCH", "VISUAL_REJECTED",
                      "AI_REFERENCE_NOT_PHOTOGRAPH"):
            self.assertIn(error, errors)

    def test_candidate_metadata_is_not_rights_or_visual_approval(self):
        metadata = dict(
            sha256="stale", plu="3283", product="Apple", approval_status="CANDIDATE",
            creator="Photographer", license="CC0", attribution="Photographer",
            source_page_url="https://example.org/apple", license_url="https://example.org/cc0",
        )
        self.image.with_suffix(".png.json").write_text(json.dumps(metadata))
        _, _, errors = image_blockers(self.row, self.review, self.root)
        self.assertIn("IMAGE_RIGHTS_NOT_VERIFIED", errors)
        self.assertIn("IMAGE_VISUAL_APPROVAL_NOT_RECORDED", errors)
        self.assertIn("PROVENANCE_CHECKSUM_MISMATCH", errors)
        self.assertIn("PROVENANCE_ASSIGNMENT_MISMATCH", errors)

    def test_all_current_conditions_required_for_automated_checks(self):
        metadata = dict(
            sha256=hashlib.sha256(self.image.read_bytes()).hexdigest(),
            plu="03283", product="Apple", creator="Photographer", license="CC0",
            attribution="Photographer", source_page_url="https://example.org/apple",
            license_url="https://example.org/cc0", rights_verification_status="VERIFIED",
            visual_approval_status="APPROVED",
        )
        self.image.with_suffix(".png.json").write_text(json.dumps(metadata))
        self.assertEqual(image_blockers(self.row, self.review, self.root)[2], [])

    def test_reviews_cannot_be_applied_to_another_assignment(self):
        with patch("audit_production.read_csv", side_effect=[
                [self.row], [dict(self.review, plu="other")]]), \
                patch("audit_production.verify_booklets"), \
                patch("audit_production.audit_entries", return_value=[]):
            with self.assertRaisesRegex(ValueError, "review assignment mismatch"):
                inventory(self.root)

    def test_duplicate_group_is_a_release_blocker(self):
        with patch("audit_production.read_csv", side_effect=[[self.row], [self.review]]), \
                patch("audit_production.verify_booklets"), \
                patch("audit_production.audit_entries", return_value=[[self.row]]):
            rows, summary = inventory(self.root)
        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["prohibited_duplicate_groups"], 1)
        self.assertIn("PROHIBITED_IMAGE_REUSE", rows[0]["blockers"])


if __name__ == "__main__":
    unittest.main()
