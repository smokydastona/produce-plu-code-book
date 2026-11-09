import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import probe_image_sources as probes


class ProbeTests(unittest.TestCase):
    def test_targets_cover_sources_and_gaps(self):
        targets = list(probes.targets())
        self.assertEqual(len([t for t in targets if not t[1]]), 17)
        self.assertEqual({t[1] for t in targets if t[1]}, set(probes.GAPS))
        self.assertTrue(all(t[3].startswith("https://") for t in targets))

    def test_preserves_success_and_explicit_failure(self):
        response = io.BytesIO(b'{"tree": [{"path": "Training/Pear 1/r0.jpg"}], "truncated": true}')
        response.url = "https://api.github.com/tree"
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        targets = [
            ("fruits360-tree", "", "", response.url),
            ("loc", "433", "white acorn squash", "https://www.loc.gov/pictures/"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "evidence"
            with patch.object(probes, "targets", return_value=targets), \
                    patch.object(probes, "urlopen", side_effect=[response, URLError("DNS")]), \
                    patch.object(probes.time, "sleep"):
                self.assertEqual(probes.probe(output, "test"), 1)
            with (output / "source-probes.csv").open() as file:
                rows = list(csv.DictReader(file))
            self.assertEqual([r["status"] for r in rows], ["FETCHED_UNVERIFIED", "ERROR"])
            self.assertIn("truncated", rows[0]["details"])
            self.assertIn("DNS", rows[1]["details"])
            self.assertTrue((output / rows[0]["response_file"]).exists())
            self.assertIn("Pear 1", (output / "fruits360-classes.json").read_text())
            with self.assertRaises(ValueError):
                probes.probe(output, "test")


if __name__ == "__main__":
    unittest.main()
