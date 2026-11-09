import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import candidate_manifest as candidates


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.entry = {
            "id": "009", "plu": "3283", "product": "Honeycrisp apple",
            "image_url": "https://upload.wikimedia.org/example.jpg",
            "source_page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
            "license": "CC0 (unverified)",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
        self.manifest = self.root / "candidates.json"

    def write(self, records):
        self.manifest.write_text(json.dumps(records))

    def test_checklist_and_manifest(self):
        self.write([self.entry])
        parsed = candidates.read_manifest(self.manifest)
        text = candidates.render(parsed)
        self.assertIn("PLU 3283: Honeycrisp apple", text)
        self.assertIn("![Candidate preview](https://upload.wikimedia.org/example.jpg)", text)
        self.assertEqual(text.count("- [ ]"), 3)
        self.assertIn("unverified", text)

    def test_rejects_bad_urls_and_duplicate_ids(self):
        for url in ("http://upload.wikimedia.org/a", "https://example.com/a",
                    "https://upload.wikimedia.org@evil.example/a"):
            self.write([{**self.entry, "image_url": url}])
            with self.assertRaises(ValueError):
                candidates.read_manifest(self.manifest)
        self.write([self.entry, self.entry])
        with self.assertRaises(ValueError):
            candidates.read_manifest(self.manifest)

    def test_download_checks_shortest_side_and_preserves_partial_success(self):
        entries = [self.entry, {**self.entry, "id": "027", "plu": "3016"}]
        calls = iter([(500, 600), (499, 900)])

        def fake_curl(command, check):
            Image.new("RGB", next(calls)).save(command[command.index("--output") + 1], format="JPEG")

        with patch.object(candidates.subprocess, "run", side_effect=fake_curl):
            failures = candidates.download(entries, self.root / "out")
        self.assertEqual(len(failures), 1)
        self.assertTrue((self.root / "out" / "009_3283.jpg").exists())
        self.assertFalse((self.root / "out" / "027_3016.jpg").exists())

    def test_download_failure_is_reported(self):
        with patch.object(candidates.subprocess, "run", side_effect=subprocess.CalledProcessError(22, "curl")):
            self.assertEqual(len(candidates.download([self.entry], self.root / "out")), 1)

    def test_empty_manifest_fails_download(self):
        self.write([])
        with patch("sys.argv", ["candidate_manifest.py", str(self.manifest),
                               "--markdown", str(self.root / "out.md"),
                               "--download-dir", str(self.root / "images")]):
            self.assertEqual(candidates.main(), 1)
        self.assertIn("No candidates supplied", (self.root / "out.md").read_text())

    def test_commit_guard_blocks_staged_data_unless_authorized(self):
        import os
        hook = Path(__file__).parent / "hooks" / "pre-commit"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "data").mkdir()
        (self.root / "data" / "review_notes.txt").write_text("change")
        subprocess.run(["git", "-C", str(self.root), "add", "data/review_notes.txt"], check=True)
        env = os.environ.copy()
        env.pop("ALLOW_REGISTER_UPDATE", None)
        blocked = subprocess.run(["sh", str(hook.resolve())], cwd=self.root, env=env,
                                 capture_output=True)
        self.assertNotEqual(blocked.returncode, 0)
        env["ALLOW_REGISTER_UPDATE"] = "1"
        allowed = subprocess.run(["sh", str(hook.resolve())], cwd=self.root, env=env)
        self.assertEqual(allowed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
