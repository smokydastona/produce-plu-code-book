import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from used_image_library import absorb_used_library, check_used_library, jpeg_copy, record_images


class UsedImageLibraryChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        original = io.BytesIO()
        Image.new("RGBA", (100, 50), (255, 0, 0, 128)).save(original, format="PNG")
        self.content = original.getvalue()

    def test_jpeg_is_white_padded_and_reused_without_encoding_or_rewriting(self):
        path, content, reused = jpeg_copy(self.root, self.content)
        self.assertFalse(reused)
        modified = path.stat().st_mtime_ns
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual((image.format, image.mode, image.size), ("JPEG", "RGB", (500, 500)))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            red, green, blue = image.getpixel((250, 250))
            self.assertGreater(red, 240)
            self.assertTrue(115 < green < 140 and 115 < blue < 140)
        with patch("used_image_library.display_image", side_effect=AssertionError("must reuse")):
            self.assertEqual(jpeg_copy(self.root, self.content), (path, content, True))
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_changed_source_and_organic_rendering_have_distinct_copies(self):
        first, _, _ = jpeg_copy(self.root, self.content)
        changed = io.BytesIO()
        Image.new("RGB", (100, 50), "blue").save(changed, format="PNG")
        second, _, reused = jpeg_copy(self.root, changed.getvalue())
        organic, _, _ = jpeg_copy(self.root, self.content, organic=True)
        self.assertFalse(reused)
        self.assertEqual(len({first, second, organic}), 3)
        self.assertEqual(len(check_used_library(self.root)), 3)

    def test_tampered_or_incomplete_cache_is_reported_not_repaired(self):
        path, _, _ = jpeg_copy(self.root, self.content)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            jpeg_copy(self.root, self.content)
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            check_used_library(self.root)
        path.unlink()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            jpeg_copy(self.root, self.content)

    def test_unapproved_associations_remain_separate_and_missing_images_stay_blank(self):
        record = dict(source_id="exact-identity", plu="00042", product="AI Apple",
                      image_status="SUPPLIED_AI_CROP_REVIEW", rights_status="NOT_VERIFIED")
        images = {"exact-identity": self.content}
        records = [record, dict(record, source_id="rejected-identity", image_status="REJECTED")]
        result = record_images(self.root, "WORKING_LIST_IMAGES.json", images, records)
        self.assertEqual(result, dict(images=1, reused=0))
        index = self.root / "sources/image-library/WORKING_LIST_IMAGES.json"
        associations = json.loads(index.read_text())
        self.assertEqual(len(associations), 1)
        self.assertEqual(associations[0]["plu"], "00042")
        self.assertEqual(associations[0]["image_status"], record["image_status"])
        self.assertEqual(associations[0]["rights_status"], "NOT_VERIFIED")
        self.assertEqual(associations[0]["library_approval_status"], "NOT_APPROVED")
        modified = index.stat().st_mtime_ns
        self.assertEqual(record_images(self.root, index.name, images, records)["reused"], 1)
        self.assertEqual(index.stat().st_mtime_ns, modified)
        self.assertEqual(len(check_used_library(self.root)), 1)
        associations[0]["library_sha256"] = "altered"
        index.write_text(json.dumps(associations))
        with self.assertRaisesRegex(ValueError, "association checksum mismatch"):
            check_used_library(self.root)

    def previous_library(self):
        record_images(self.root, "WORKING_LIST_IMAGES.json", {"identity": self.content}, [
            dict(source_id="identity", plu="00042", rights_status="NOT_VERIFIED")
        ])
        current = self.root / "sources/image-library"
        previous = self.root / "sources/used-image-library"
        current.rename(previous)
        index = previous / "WORKING_LIST_IMAGES.json"
        records = json.loads(index.read_text())
        records[0]["library_image"] = "sources/used-image-library/" + Path(records[0]["library_image"]).name
        index.write_text(json.dumps(records))
        return previous, records[0]

    def test_absorption_preserves_bytes_and_review_status_and_removes_second_directory(self):
        previous, record = self.previous_library()
        filename = Path(record["library_image"]).name
        original = (previous / filename).read_bytes()
        absorb_used_library(self.root)
        self.assertFalse(previous.exists())
        library = self.root / "sources/image-library"
        self.assertEqual((library / filename).read_bytes(), original)
        association = json.loads((library / "WORKING_LIST_IMAGES.json").read_text())[0]
        self.assertEqual(association["library_image"], "sources/image-library/" + filename)
        self.assertEqual(association["rights_status"], "NOT_VERIFIED")
        self.assertEqual(len(check_used_library(self.root)), 1)
        absorb_used_library(self.root)

    def test_absorption_refuses_collisions_without_removing_previous_assets(self):
        previous, record = self.previous_library()
        library = self.root / "sources/image-library"
        library.mkdir()
        filename = Path(record["library_image"]).name
        (library / filename).write_bytes(b"unmanaged")
        with self.assertRaisesRegex(ValueError, "merge collision"):
            absorb_used_library(self.root)
        self.assertTrue((previous / filename).exists())
        self.assertEqual((library / filename).read_bytes(), b"unmanaged")


if __name__ == "__main__":
    unittest.main()
