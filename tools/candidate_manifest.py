"""Generate a human-review checklist or download candidates from a JSON manifest."""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

REQUIRED = ("id", "plu", "product", "source_page_url")


def https_url(value, *, image=False):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port not in (None, 443)
                or any(c.isspace() or c in "<>\\" for c in value)):
            return False
        return not image or parsed.hostname.lower() == "upload.wikimedia.org"
    except ValueError:
        return False


def read_manifest(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("manifest must be a JSON array")
    seen = set()
    for candidate in data:
        if not isinstance(candidate, dict) or any(
            not isinstance(candidate.get(k), str) or not candidate[k].strip()
            for k in REQUIRED
        ):
            raise ValueError("each candidate requires nonempty string fields: " + ", ".join(REQUIRED))
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", candidate["id"]):
            raise ValueError("candidate id must contain only letters, numbers, underscores or hyphens")
        if candidate["id"] in seen:
            raise ValueError(f"duplicate candidate id: {candidate['id']}")
        seen.add(candidate["id"])
        if not re.fullmatch(r"[0-9]+", candidate["plu"]):
            raise ValueError("PLU must contain only digits")
        source = urlsplit(candidate["source_page_url"])
        if not https_url(candidate["source_page_url"]) or source.hostname != "commons.wikimedia.org":
            raise ValueError(f"invalid source_page_url for {candidate['id']}")
        if candidate.get("image_url") and not https_url(candidate["image_url"], image=True):
            raise ValueError(f"invalid or unsupported image_url for {candidate['id']}")
        if candidate.get("license_url") and not https_url(candidate["license_url"]):
            raise ValueError(f"invalid or unsupported license_url for {candidate['id']}")
    return data


def escaped(text):
    return re.sub(r"([\\`*_{}\[\]<>#!|])", r"\\\1", text.replace("\n", " ").replace("\r", " "))


def render(candidates):
    lines = ["# Unreviewed produce image candidates", "",
             "All licences and images are unverified leads. No candidate is approved.", ""]
    if not candidates:
        lines += ["No candidates supplied.", ""]
    for c in candidates:
        lines += [
            f"### PLU {c['plu']}: {escaped(c['product'])} ({escaped(c['id'])})",
            "",
            (f"![Candidate preview]({c['image_url']})" if c.get("image_url")
             else f"[Source page / preview]({c['source_page_url']})"),
            "",
            (f"[Source page]({c['source_page_url']})" +
             (f" | [Suspected licence: {escaped(c['license'])}]({c['license_url']})"
              if c.get("license") and c.get("license_url") else " | Licence not checked")),
            "",
            "- [ ] **Visual review:** photograph of the correct variety, without watermarks or artifacts",
            "- [ ] **Rights review:** creator and commercial reuse rights verified at the source",
            "- [ ] **Technical review:** at least 500 px on the shortest side",
            "",
        ]
    return "\n".join(lines)


def download(candidates, output):
    output.mkdir(parents=True, exist_ok=True)
    failures = []
    for c in candidates:
        try:
            if not c.get("image_url"):
                raise ValueError("direct image_url is required by this downloader")
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "download"
                subprocess.run([
                    "curl", "--fail", "--silent", "--show-error", "--proto", "=https",
                    "--max-filesize", "50000000", "--max-time", "60",
                    "--output", str(path), "--", c["image_url"],
                ], check=True)
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        if image.format not in ("JPEG", "PNG", "WEBP"):
                            raise ValueError("only JPEG, PNG and WebP files are supported")
                        if getattr(image, "n_frames", 1) != 1:
                            raise ValueError("animated images are not supported")
                        if min(image.size) < 500:
                            raise ValueError(f"shortest side is {min(image.size)} px")
                        extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[image.format]
                        image.verify()
                    with Image.open(path) as image:
                        image.load()
                target = output / f"{c['id']}_{c['plu']}.{extension}"
                with target.open("xb") as file:
                    file.write(path.read_bytes())
                print(f"PASS {c['id']}: {target} (unreviewed)")
        except (OSError, ValueError, subprocess.CalledProcessError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            failures.append(f"{c['id']}: {exc}")
            print(f"FAIL {failures[-1]}", file=sys.stderr)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path)
    args = parser.parse_args()
    try:
        candidates = read_manifest(args.manifest)
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render(candidates), encoding="utf-8")
        if args.download_dir:
            if not candidates:
                raise ValueError("manifest has no candidates")
            if download(candidates, args.download_dir):
                return 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
