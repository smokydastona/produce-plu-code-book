"""Download public-domain Commons candidates; never approve or replace booklet images."""
import argparse
import hashlib
import html
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from PIL import Image

from verify_images import PUBLIC_DOMAIN, validate

API = "https://commons.wikimedia.org/w/api.php"
TARGETS = {"3283": "Honeycrisp apple", "3016": "Concorde pear", "4555": "Savoy cabbage"}


def plain(value):
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def fetch(url, user_agent):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "commons.wikimedia.org", "upload.wikimedia.org"
    }:
        raise ValueError(f"unexpected Wikimedia URL: {url}")
    with urlopen(Request(url, headers={"User-Agent": user_agent}), timeout=60) as response:
        data = response.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024:
            raise ValueError("response exceeds 50 MiB")
        return data


def search(product, user_agent):
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f'"{product}" filetype:bitmap', "gsrnamespace": 6,
        "gsrlimit": 50, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    response = json.loads(fetch(API + "?" + urlencode(params), user_agent))
    if "error" in response:
        raise ValueError(f"Commons API error: {response['error']}")
    return sorted(response.get("query", {}).get("pages", {}).values(),
                  key=lambda page: page.get("index", 0))


def download(plu, product, output, user_agent):
    for page in search(product, user_agent):
        info = page.get("imageinfo", [{}])[0]
        extra = info.get("extmetadata", {})
        get = lambda key: plain(extra.get(key, {}).get("value", ""))
        license_name = get("LicenseShortName")
        if license_name == "CC0 1.0":
            license_name = "CC0"
        if license_name not in PUBLIC_DOMAIN or get("Restrictions"):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 500:
            continue
        suffix = {"image/jpeg": ".jpg", "image/png": ".png"}.get(info.get("mime"))
        if not suffix or not get("Artist") or not get("LicenseUrl"):
            continue
        url = info["url"]
        content = fetch(url, user_agent)
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
        if min(width, height) < 500:
            continue
        path = output / f"{plu}{suffix}"
        sidecar = path.with_suffix(suffix + ".json")
        if list(output.glob(f"{plu}.*")):
            raise FileExistsError(f"candidate already exists for PLU {plu}; will not overwrite")
        license_url = get("LicenseUrl")
        if license_url.startswith("//"):
            license_url = "https:" + license_url
        metadata = {
            "plu": plu, "product": product, "creator": get("Artist"),
            "license": license_name, "license_url": license_url,
            "source_page_url": info["descriptionurl"], "original_image_url": url,
            "width": width, "height": height,
            "attribution": f"{get('Artist')} / {page['title']} / {license_name}",
            "approval_status": "CANDIDATE",
            "visual_verification": "NOT REVIEWED",
            "description": get("ImageDescription"),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        output.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(content)
        with sidecar.open("x", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
            file.write("\n")
        errors = validate(path)
        if errors:
            raise ValueError(f"{path}: {'; '.join(errors)}")
        print(f"Downloaded {path}; exact variety and photographic suitability NOT verified")
        return True
    print(f"UNRESOLVED {plu}: no eligible public-domain candidate for {product}", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/images/candidates"))
    parser.add_argument("--user-agent", required=True,
                        help="Descriptive Wikimedia User-Agent including a contact URL/email")
    args = parser.parse_args()
    failed = False
    for plu, product in TARGETS.items():
        try:
            if not download(plu, product, args.output, args.user_agent):
                failed = True
        except (OSError, ValueError, KeyError) as exc:
            failed = True
            print(f"ERROR {plu}: {exc}", file=sys.stderr)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
