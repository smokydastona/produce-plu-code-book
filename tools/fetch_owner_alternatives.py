"""Fetch owner-proposed image URLs as unapproved, temporary review evidence."""
import argparse
import csv
import hashlib
import io
import json
import re
import warnings
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps

MAX_BYTES = 25 * 1024 * 1024
ALLOWED_HOSTS = {
    "foxy.com", "media.koelnmesse.io", "media.sobeys.com", "chefsmandala.com",
    "i5.walmartimages.ca", "gmfgcdn.azureedge.net", "specialtyproduce.com",
    "m.media-amazon.com", "storage.googleapis.com", "vicinitymart.com",
    "images.cdn.saveonfoods.com", "encrypted-tbn0.gstatic.com", "www.naturespride.eu",
}


def validate_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f"URL outside approved HTTPS hosts: {url}")


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def save_image(data, output, plu):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("multi-frame image")
            image.load()
            extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(image.format)
            if extension is None:
                raise ValueError(f"unsupported image format: {image.format}")
            width, height = image.size
            name = plu + extension
            (output / name).write_bytes(data)
            mirrored = ""
            if plu == "4885":
                mirrored = "4885-mirrored.png"
                ImageOps.mirror(ImageOps.exif_transpose(image)).save(output / mirrored)
    return name, width, height, mirrored


def acquire(manifest, output):
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest must contain a nonempty list")
    seen = set()
    for entry in entries:
        if not re.fullmatch(r"\d+", entry["plu"]) or entry["plu"] in seen:
            raise ValueError(f"invalid or duplicate PLU: {entry['plu']}")
        seen.add(entry["plu"])
        validate_url(entry["url"])
    output.mkdir(parents=True, exist_ok=False)
    opener = build_opener(SafeRedirect())
    report = []
    for entry in entries:
        row = dict(entry, status="ERROR", detail="", final_url="", content_type="",
                   image_file="", sha256="", width="", height="", mirrored_file="",
                   mirrored_sha256="", rights="NOT_VERIFIED", production_approval="NOT_APPROVED")
        try:
            request = Request(entry["url"], headers={"User-Agent": "ProducePLUReferenceReview/1.0"})
            with opener.open(request, timeout=30) as response:
                row["final_url"] = response.url
                row["content_type"] = response.headers.get("Content-Type", "")
                content = response.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError("response exceeds 25 MiB")
            name, width, height, mirrored = save_image(content, output, entry["plu"])
            row.update(status="FETCHED_UNVERIFIED", image_file=name,
                       sha256=hashlib.sha256(content).hexdigest(), width=width, height=height,
                       mirrored_file=mirrored)
            if mirrored:
                row["mirrored_sha256"] = hashlib.sha256((output / mirrored).read_bytes()).hexdigest()
        except (HTTPError, URLError, OSError, ValueError, Image.DecompressionBombWarning,
                Image.DecompressionBombError) as exc:
            row["detail"] = str(exc)
        report.append(row)
        print(f"{entry['plu']} {entry['product']}: {row['status']} {row['detail']}", flush=True)
    with (output / "FETCH_REPORT.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(report[0]))
        writer.writeheader()
        writer.writerows(report)
    (output / "README.txt").write_text(
        "Unapproved reference candidates only; source rights, product identity, resolution and "
        "production use have not been verified. The basil PNG is a horizontal mirror of the "
        "EXIF-oriented downloaded original. Originals have not been altered.\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = acquire(args.manifest, args.output)
    if any(row["status"] != "FETCHED_UNVERIFIED" for row in report):
        raise SystemExit("Some URLs failed; see FETCH_REPORT.csv for individual results.")


if __name__ == "__main__":
    main()
