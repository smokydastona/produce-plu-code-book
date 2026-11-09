"""Fetch Commons' image metadata for the candidate source pages."""
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from candidate_manifest import read_manifest


def main(manifest, destination):
    results = []
    failed = False
    for candidate in read_manifest(manifest):
        source = urlsplit(candidate["source_page_url"])
        if source.hostname != "commons.wikimedia.org" or not source.path.startswith("/wiki/File:"):
            print(f"Unsupported Commons file page: {candidate['source_page_url']}", file=sys.stderr)
            failed = True
            continue
        title = unquote(source.path[len("/wiki/"):]).replace("_", " ")
        query = urlencode({
            "action": "query", "format": "json", "titles": title,
            "prop": "imageinfo", "iiprop": "url|size|sha1|extmetadata",
        })
        try:
            request = Request("https://commons.wikimedia.org/w/api.php?" + query,
                              headers={"User-Agent": "ProducePLUReview/1.0 (https://github.com/smokydastona/produce-plu-code-book)"})
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
            if "error" in data:
                raise ValueError(f"Commons API error: {data['error']}")
            page = next(iter(data["query"]["pages"].values()))
            info = page["imageinfo"][0]
            api_url = urlsplit(info["url"])
            supplied_url = urlsplit(candidate["image_url"]) if candidate.get("image_url") else None
            if supplied_url and (api_url.scheme, api_url.netloc, api_url.path) != (
                    supplied_url.scheme, supplied_url.netloc, supplied_url.path):
                raise ValueError(f"image URL differs from Commons record: {info['url']}")
            results.append({"candidate_id": candidate["id"], "page": page})
            print(f"Metadata retrieved for {candidate['id']}")
        except (OSError, ValueError, KeyError, StopIteration) as exc:
            failed = True
            print(f"Metadata error for {candidate['id']}: {exc}", file=sys.stderr)
    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
