"""Validate candidate image files and their adjacent .json provenance records."""
import argparse
import json
import warnings
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

PUBLIC_DOMAIN = {"CC0", "Public domain"}
LICENSES = PUBLIC_DOMAIN | {"CC BY 2.0", "CC BY 3.0", "CC BY 4.0",
                            "CC BY-SA 3.0", "CC BY-SA 4.0"}
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".gif",
              ".bmp", ".avif", ".svg"}


def validate(path):
    errors = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                size = image.size
                if min(size) < 500:
                    errors.append(f"shortest side is {min(size)} px; minimum is 500")
                if getattr(image, "n_frames", 1) != 1:
                    errors.append("animated/multiframe images are not supported")
                image.verify()
            with Image.open(path) as image:
                image.load()
    except (OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        return [f"invalid image: {exc}"]
    try:
        metadata = json.loads(path.with_suffix(path.suffix + ".json").read_text())
    except (OSError, ValueError) as exc:
        return errors + [f"missing or invalid provenance JSON: {exc}"]
    if not isinstance(metadata, dict):
        return errors + ["provenance JSON must be an object"]
    for key in ("plu", "product", "creator", "license", "attribution",
                "source_page_url", "original_image_url", "license_url"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            errors.append(f"missing/non-string metadata: {key}")
    for key in ("source_page_url", "original_image_url", "license_url"):
        value = metadata.get(key)
        if isinstance(value, str):
            try:
                url = urlparse(value)
                valid_url = url.scheme == "https" and bool(url.hostname)
            except ValueError:
                valid_url = False
            if not valid_url:
                errors.append(f"{key} must be an absolute HTTPS URL")
    if metadata.get("license") not in LICENSES:
        errors.append("licence is not a supported commercial-use licence")
    if metadata.get("width") != size[0] or metadata.get("height") != size[1]:
        errors.append("recorded dimensions do not match the file")
    if metadata.get("approval_status") != "CANDIDATE":
        errors.append("approval_status must be CANDIDATE; automated checks do not approve photos")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", type=Path)
    parser.add_argument("--changed-from", help="Git base commit; check added/modified images only")
    args = parser.parse_args()
    paths = args.images
    if args.changed_from:
        import subprocess
        base = subprocess.check_output([
            "git", "merge-base", args.changed_from, "HEAD",
        ]).decode().strip()
        names = subprocess.check_output([
            "git", "diff", "--name-only", "-z", "--diff-filter=AMRD",
            base, "HEAD", "--", "data/images", "sources",
        ]).decode().split("\0")
        for name in filter(None, names):
            path = Path(name)
            if path.suffix.lower() == ".json":
                path = path.with_suffix("")
            if path.suffix.lower() in EXTENSIONS and path.is_file():
                paths.append(path)
    failed = False
    for path in sorted(set(paths)):
        errors = validate(path)
        if errors:
            failed = True
            print(f"FAIL {path}: {'; '.join(errors)}")
        else:
            print(f"PASS {path} (technical checks only; visual review still required)")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
