import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from retrieve_commons import acquire
from used_image_library import record_images


class LocalAcquisitionChecks(unittest.TestCase):
    def test_local_priority_and_identity_match_prevent_network_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = dict(idx="1", source_id="identity", plu="00042", name="Apple")
            for tier in ("NOT_APPROVED", "APPROVED_LEGACY", "APPROVED"):
                image = io.BytesIO()
                Image.new("RGB", (100, 100), "red").save(image, format="PNG")
                record_images(root, "WORKING_LIST_IMAGES.json", {"identity": image.getvalue()}, [
                    dict(source_id="identity", plu="00042", product="Apple",
                         library_approval_status=tier, image_status="SUPPLIED_REFERENCE_REVIEW",
                         rights_status="NOT_VERIFIED"),
                ])
                output = root / tier
                with patch("retrieve_commons.search", side_effect=AssertionError("no network")):
                    self.assertFalse(acquire([entry], output, "test", 2, root=root))
                records = json.loads((output / "provenance.json").read_text())
                self.assertEqual(records[0]["approval_status"], tier)
                self.assertEqual(records[0]["provenance"]["rights_status"], "NOT_VERIFIED")
            changed = dict(entry, source_id="changed")
            with patch("retrieve_commons.search", return_value=[]) as search:
                self.assertFalse(acquire([changed], root / "changed", "test", 1, root=root))
            search.assert_called_once()

    def test_approved_beats_legacy_and_reviewed_then_legacy_beats_reviewed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = dict(idx="1", plu="00042", name="Apple")
            image = io.BytesIO()
            Image.new("RGB", (100, 100), "red").save(image, format="PNG")
            record_images(root, "LEGACY_BOOKLET_IMAGES.json", {"legacy:1": image.getvalue()}, [
                dict(source_id="legacy:1", plu="00042", name="Apple",
                     library_approval_status="APPROVED_LEGACY"),
            ])
            for status, expected in (("APPROVED", "APPROVED"), ("NOT_APPROVED", "APPROVED_LEGACY")):
                record_images(root, "WORKING_LIST_IMAGES.json", {"current": image.getvalue()}, [
                    dict(source_id="current", plu="00042", product="Apple",
                         library_approval_status=status),
                ])
                output = root / status
                with patch("retrieve_commons.search", side_effect=AssertionError("no network")):
                    self.assertFalse(acquire([entry], output, "test", 1, root=root))
                record = json.loads((output / "provenance.json").read_text())[0]
                self.assertEqual(record["approval_status"], expected)

    def test_missing_local_image_searches_online_and_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = dict(idx="1", plu="00042", name="Apple")
            with patch("retrieve_commons.search", return_value=[]) as search:
                self.assertFalse(acquire([entry], root / "missing", "test", 1, root=root))
            search.assert_called_once()
            image = io.BytesIO()
            Image.new("RGB", (100, 100), "red").save(image, format="PNG")
            record_images(root, "WORKING_LIST_IMAGES.json", {"identity": image.getvalue()}, [
                dict(source_id="identity", plu="00042", product="Apple"),
            ])
            asset = next((root / "sources/image-library").glob("*.jpg"))
            asset.write_bytes(b"corrupt")
            with patch("retrieve_commons.search", side_effect=AssertionError("no network")):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    acquire([entry], root / "corrupt", "test", 1, root=root)

    def test_changed_assignment_cannot_reuse_stale_library_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = io.BytesIO()
            Image.new("RGB", (100, 100), "red").save(image, format="PNG")
            record_images(root, "WORKING_LIST_IMAGES.json", {"identity": image.getvalue()}, [
                dict(source_id="identity", plu="00042", product="Apple",
                     library_approval_status="APPROVED", assignment={"source_id": "identity"}),
            ])
            (root / "data").mkdir()
            (root / "data/picklist_assignments.json").write_text(json.dumps({
                "assignments": [{"source_id": "identity", "visual_approval_status": "NOT_APPROVED"}],
            }))
            with patch("retrieve_commons.search", side_effect=AssertionError("no network")):
                with self.assertRaisesRegex(ValueError, "stale local working image assignment"):
                    acquire([dict(idx="1", source_id="identity", plu="00042", name="Apple")],
                            root / "stale", "test", 1, root=root)


if __name__ == "__main__":
    unittest.main()
