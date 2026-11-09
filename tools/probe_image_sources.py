"""Probe alternative libraries and preserve discovery responses, not approved images."""
import argparse
import csv
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCES = {
    "commons": "https://commons.wikimedia.org/wiki/Main_Page",
    "flickr": "https://www.flickr.com/creativecommons/",
    "europeana": "https://www.europeana.eu/",
    "rawpixel": "https://www.rawpixel.com/",
    "publicdomainpictures": "https://www.publicdomainpictures.net/",
    "pexels": "https://www.pexels.com/",
    "usda": "https://www.usda.gov/",
    "ars": "https://www.ars.usda.gov/",
    "nal": "https://www.nal.usda.gov/",
    "loc": "https://www.loc.gov/pictures/",
    "archives": "https://catalog.archives.gov/",
    "fruits360": "https://github.com/fruits-360/fruits-360-original-size",
    "fruit-images": "https://github.com/Horea94/Fruit-Images-Dataset",
    "veggies": "https://github.com/jscastanos/veggies",
    "foodiesfeed": "https://foodiesfeed.com/",
    "imagescv": "https://images.cv/",
}
GAPS = {
    "361": "mini white potato", "368": "white creamer potato",
    "370": "yellow creamer potato", "433": "white acorn squash",
}


def targets():
    for source, url in SOURCES.items():
        yield source, "", "", url
    for idx, query in GAPS.items():
        searches = {
            "commons": "https://commons.wikimedia.org/w/api.php?" + urlencode({
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f'"{query}" filetype:bitmap', "gsrnamespace": 6,
                "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|size|extmetadata",
            }),
            "flickr": "https://www.flickr.com/search/?" + urlencode({"text": query}),
            "loc": "https://www.loc.gov/pictures/?" + urlencode({"q": query, "fo": "json"}),
            "europeana": "https://www.europeana.eu/en/search?" + urlencode({"query": query}),
            "ars": "https://www.ars.usda.gov/oc/images/image-gallery/?" + urlencode({"q": query}),
            "publicdomainpictures": "https://www.publicdomainpictures.net/en/hledej.php?" + urlencode({"hleda": query}),
        }
        for source, url in searches.items():
            yield source, idx, query, url
    yield (
        "fruits360-tree", "", "",
        "https://api.github.com/repos/fruits-360/fruits-360-original-size/git/trees/main?recursive=1",
    )


def probe(output, user_agent):
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("probe output must be empty; evidence will not be overwritten")
    fields = ["source", "idx", "query", "requested_url", "final_url", "http_status",
              "status", "content_type", "response_file", "details"]
    failures = 0
    with (output / "source-probes.csv").open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for number, (source, idx, query, url) in enumerate(targets(), 1):
            row = dict.fromkeys(fields, "")
            row.update(source=source, idx=idx, query=query, requested_url=url)
            try:
                request = Request(url, headers={"User-Agent": user_agent})
                with urlopen(request, timeout=30) as response:
                    row.update(final_url=response.url, http_status=response.status,
                               content_type=response.headers.get("Content-Type", ""))
                    data = response.read(25 * 1024 * 1024 + 1)
                    if len(data) > 25 * 1024 * 1024:
                        raise ValueError("response exceeds 25 MiB; not saved")
                suffix = ".json" if "json" in row["content_type"] else ".html"
                name = f"{number:02d}-{source}-{idx or 'index'}{suffix}"
                (output / name).write_bytes(data)
                row.update(status="FETCHED_UNVERIFIED", response_file=name,
                           details="HTTP success is not proof of search results or usable image rights")
                if source == "fruits360-tree":
                    tree = json.loads(data)
                    if tree.get("truncated"):
                        row["details"] += "; GitHub tree is truncated"
                    folders = sorted({
                        entry["path"].split("/")[1]
                        for entry in tree.get("tree", [])
                        if entry["path"].startswith("Training/")
                        and len(entry["path"].split("/")) > 2
                    })
                    (output / "fruits360-classes.json").write_text(
                        json.dumps(folders, indent=2) + "\n", encoding="utf-8")
            except HTTPError as exc:
                failures += 1
                row.update(status="ERROR", http_status=exc.code, details=str(exc))
            except (URLError, OSError, ValueError) as exc:
                failures += 1
                row.update(status="ERROR", details=str(exc))
            writer.writerow(row)
            file.flush()
            print(f"{source} {idx}: {row['status']} {row['details']}", flush=True)
            time.sleep(2)
    (output / "REVIEW.txt").write_text(
        "Discovery evidence only. No image approved or production register changed.\n"
        "Some endpoints may ignore queries or return bot challenges despite HTTP 200.\n"
        "Review actual results and individual file rights, creator, source, original "
        "dimensions and exact produce identity before acquiring or using an image.\n"
        f"Failed probes: {failures}. See source-probes.csv for every result.\n",
        encoding="utf-8",
    )
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    args = parser.parse_args()
    try:
        failures = probe(args.output, args.user_agent)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
