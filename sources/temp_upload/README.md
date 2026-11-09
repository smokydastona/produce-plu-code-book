# Temporary image uploads

Upload candidate replacement photos here before they are reviewed and sorted into the project.

For each photo, use a filename that identifies the rejected entry, such as `009_honeycrisp.jpg` or `465_napa-cabbage.jpg`. If one photo is intended for multiple entries, identify each entry in a companion note.

Include the original source-page URL, creator, licence, and any required attribution for every image. Keep the original file unchanged; do not crop, resize, or approve it here. Images remain candidates until their variety, dimensions, and reuse rights have been checked.

Eligible licence types are CC0 1.0, CC BY 2.0/3.0/4.0, CC BY-SA 2.0/3.0/4.0, and verified public-domain works. See the [image licence policy](../../README.md#replacement-image-retrieval-and-checks) for attribution and share-alike conditions. Neither a Commons download link nor a Public Domain Mark alone establishes rights. Each acquisition package includes a `license-register.csv` separating licence-type eligibility, individual rights verification, and visual approval; no status is automatically approved.

After review, approved images will be moved to their final locations and this temporary folder can be emptied.

For Wikimedia downloads through GitHub Actions, add candidate file pages to `candidates.json` as a JSON array. Each object needs `id` (a unique filename-safe identifier), `plu` (a string), `product`, and `source_page_url`. The workflow retrieves the canonical original image URL and licence metadata from the Commons API; do not guess these values. Optional `image_url`, `license`, and `license_url` fields are accepted when known and must be accurate. URLs must be HTTPS. Example:

```json
[
  {
    "id": "009",
    "plu": "3283",
    "product": "Apples Honey Crisp",
    "source_page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg"
  }
]
```

`candidates.json` contains source-specific leads, not approved photographs. Run `python3 tools/candidate_manifest.py sources/temp_upload/candidates.json --markdown candidates_manifest.md` to generate a review checklist locally.

The manually triggered **Fetch unreviewed produce candidates** workflow now uses `retrieve_commons.py --review` to search all 31 rejected entries, trying the known source pages first. It accepts supported CC BY and CC BY-SA licences as well as public-domain declarations, but requires creator metadata. Its downloadable artifact contains unchanged originals, provenance, contact sheets and an acquisition report for all entries. UNRESOLVED means no eligible candidate; ERROR means acquisition failed and the workflow fails. Neither a successful download nor a successful run approves an image. Production registers and booklet images remain untouched.
