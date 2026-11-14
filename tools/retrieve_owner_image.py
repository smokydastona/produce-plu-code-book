"""Fetch one owner-provided image into an identity-pinned review artifact."""
import argparse
import csv
import hashlib
import io
import json
import warnings
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

from retrieve_commons import current_review_rejections, select_review_sequence
from working_list import read_working_list

GOOGLE_HOSTS = (
    "google.com",
    "googleusercontent.com",
    "photos.app.goo.gl",
    "photos.google.com",
)
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024
IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
OWNER_RIGHTS_EVIDENCE = (
    'User attestation: "I own this image and all the rights to it so I approve it completely"'
)


def is_google_https_url(value):
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and any(host == suffix or host.endswith("." + suffix) for suffix in GOOGLE_HOSTS)
        )
    except ValueError:
        return False


class GoogleRedirectHandler(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, response, code, message, headers, new_url):
        if not is_google_https_url(new_url):
            raise ValueError("Google Photos link redirects outside the allowed Google HTTPS hosts")
        return super().redirect_request(request, response, code, message, headers, new_url)


class OpenGraphImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image_url = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "meta" or self.image_url:
            return
        attributes = dict(attrs)
        property_name = (attributes.get("property") or attributes.get("name") or
                         attributes.get("itemprop") or "").lower()
        if property_name in {"og:image", "og:image:url", "twitter:image"}:
            self.image_url = attributes.get("content", "")


def fetch_google_url(url, user_agent):
    if not is_google_https_url(url):
        raise ValueError("image URL must use HTTPS on a Google Photos/Googleusercontent host")
    request = Request(url, headers={"User-Agent": user_agent})
    opener = build_opener(GoogleRedirectHandler())
    with opener.open(request, timeout=30) as response:
        final_url = response.geturl()
        if not is_google_https_url(final_url):
            raise ValueError("final image URL is outside the allowed Google HTTPS hosts")
        content = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("download exceeds the 30 MiB safety limit")
        return content, response.headers.get_content_type(), final_url


def image_url_from_html(content, page_url):
    parser = OpenGraphImageParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    if not parser.image_url:
        raise ValueError("Google Photos page did not expose a public image preview")
    image_url = urljoin(page_url, parser.image_url)
    if not is_google_https_url(image_url):
        raise ValueError("Google Photos image preview URL is outside the allowed Google HTTPS hosts")
    return image_url


def retrieve_image(url, user_agent, fetch=fetch_google_url):
    content, content_type, final_url = fetch(url, user_agent)
    if content_type in {"text/html", "application/xhtml+xml"}:
        image_url = image_url_from_html(content, final_url)
        content, content_type, final_url = fetch(image_url, user_agent)
    if not content_type.startswith("image/"):
        raise ValueError(f"Google Photos returned unsupported content type: {content_type}")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                if image_format not in IMAGE_EXTENSIONS:
                    raise ValueError(f"unsupported image format: {image_format}")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("animated/multiframe images are not supported")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                width, height = image.size
                has_transparency = (
                    "A" in image.getbands() or "transparency" in image.info
                ) and image.convert("RGBA").getchannel("A").getextrema()[0] < 255
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"downloaded content is not a safe, readable image: {exc}") from exc

    if min(width, height) < 500:
        raise ValueError(f"shortest image side is {min(width, height)} px; minimum is 500")
    return {
        "content": content,
        "content_type": content_type,
        "final_url": final_url,
        "format": image_format,
        "extension": IMAGE_EXTENSIONS[image_format],
        "width": width,
        "height": height,
        "has_transparency": has_transparency,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def write_report(output, entry, source_url, status, details, metadata=None):
    row = {
        "idx": entry.get("idx", ""),
        "plu": entry.get("plu", ""),
        "product": entry.get("name", ""),
        "query": "Owner-provided image",
        "source": "Google Photos",
        "status": status,
        "details": details,
        "candidates": int(metadata is not None),
    }
    with (output / "acquisition-report.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys())
        writer.writeheader()
        writer.writerow(row)
    if metadata:
        (output / "provenance.json").write_text(
            json.dumps([metadata], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "REVIEW.txt").write_text(
            "OWNER-PROVIDED IMAGE - NOT ASSIGNED TO PRODUCTION\n"
            "The owner attested that they own the image and all rights and approved its use.\n"
            "This records owner-confirmed permission; no public licence or creator is inferred.\n"
            "Image bytes are unchanged. Verify exact product, photographic origin and background.\n"
            "No booklet or production register was modified.\n", encoding="utf-8")
    else:
        (output / "REVIEW.txt").write_text(
            f"OWNER-PROVIDED IMAGE COULD NOT BE RETRIEVED\nSource: {source_url}\n"
            f"Error: {details}\nNo production file was changed.\n", encoding="utf-8")


def retrieve(root, review_path, sequence, source_url, output, user_agent):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("review package output must be empty")
    entries = current_review_rejections(root, review_path)
    selected = select_review_sequence(entries, sequence)
    if len(selected) != 1:
        raise ValueError("owner image retrieval requires exactly one rejected review sequence")
    entry = selected[0]
    items, _ = read_working_list(root)
    working_item = next(item for item in items if item["source_id"] == entry["source_id"])
    image = retrieve_image(source_url, user_agent)
    target_dir = output / "originals" / f"{int(sequence):03d}" / "owner-provided"
    target_dir.mkdir(parents=True)
    target = target_dir / (entry["plu"] + image["extension"])
    target.write_bytes(image["content"])

    metadata = {
        "schema_version": 1,
        "sequence": sequence,
        "source_id": entry["source_id"],
        "source_identity_ids": working_item["source_ids"],
        "plu": entry["plu"],
        "product": entry["name"],
        "source_url": source_url,
        "retrieval_host": urlparse(image["final_url"]).hostname,
        "creator": "Not separately identified by the owner",
        "rights_status": "OWNER_CONFIRMED_PERMISSION",
        "rights_evidence": OWNER_RIGHTS_EVIDENCE,
        "visual_approval_status": "OWNER_APPROVED",
        "photographic_origin": "NOT_VERIFIED",
        "background_status": "TRANSPARENT" if image["has_transparency"] else "NOT_TRANSPARENT",
        "content_type": image["content_type"],
        "format": image["format"],
        "width": image["width"],
        "height": image["height"],
        "sha256": image["sha256"],
        "approval_status": "CANDIDATE",
        "image": str(target.relative_to(output)),
    }
    target.with_suffix(target.suffix + ".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(output, entry, source_url, "OWNER_PROVIDED_CANDIDATE",
                 "Owner attestation recorded; photographic origin remains unverified.", metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--working-list-review", type=Path, required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    try:
        retrieve(args.root, args.working_list_review, args.sequence, args.url,
                 args.output, args.user_agent)
    except (OSError, ValueError, KeyError) as exc:
        if not args.output.exists() or not any(args.output.iterdir()):
            args.output.mkdir(parents=True, exist_ok=True)
            write_report(args.output, {"idx": args.sequence}, args.url, "ERROR", str(exc))
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
