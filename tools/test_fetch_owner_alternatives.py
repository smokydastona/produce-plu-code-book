import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from PIL import Image, ImageOps

from fetch_owner_alternatives import acquire, save_image, validate_url


class OwnerAlternativesTest(unittest.TestCase):
    def test_basil_mirror_preserves_original(self):
        image = Image.new("RGB", (3, 2))
        image.putpixel((0, 0), (255, 0, 0))
        data = io.BytesIO()
        image.save(data, format="PNG")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            name, width, height, mirrored = save_image(data.getvalue(), output, "4885")
            self.assertEqual((name, width, height, mirrored), ("4885.png", 3, 2, "4885-mirrored.png"))
            self.assertEqual((output / name).read_bytes(), data.getvalue())
            with Image.open(output / mirrored) as result:
                self.assertEqual(list(result.getdata()), list(ImageOps.mirror(image).getdata()))

    def test_bad_redirect_host_and_scheme_are_rejected(self):
        for url in ("http://foxy.com/image.png", "https://foxy.com.evil.example/a",
                    "https://foxy.com:8443/a", "https://user@foxy.com/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_failed_fetch_is_reported_without_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([{"plu": "4885", "product": "Basil",
                                             "url": "https://foxy.com/a.png"}]))
            with patch("fetch_owner_alternatives.build_opener") as opener:
                opener.return_value.open.side_effect = URLError("unavailable")
                report = acquire(manifest, root / "output")
            self.assertEqual(report[0]["status"], "ERROR")
            self.assertEqual(report[0]["production_approval"], "NOT_APPROVED")
            with (root / "output/FETCH_REPORT.csv").open(newline="") as file:
                self.assertIn("unavailable", next(csv.DictReader(file))["detail"])

    def test_multiple_candidates_can_target_one_plu(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([
                {"plu": "4055", "product": "Murcott Tangerines", "url": "https://foxy.com/a.png"},
                {"candidate_id": "4055-melissas", "plu": "4055",
                 "product": "Murcott Tangerines", "url": "https://foxy.com/b.png"},
            ]))
            with patch("fetch_owner_alternatives.build_opener") as opener:
                opener.return_value.open.side_effect = URLError("unavailable")
                report = acquire(manifest, root / "output")
            self.assertEqual([row["candidate_id"] for row in report], ["4055", "4055-melissas"])


if __name__ == "__main__":
    unittest.main()
