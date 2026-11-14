# Temporary image uploads

Upload candidate replacement photos here before they are reviewed and sorted into the project.

For each photo, use a filename that identifies its entry, such as `009_honeycrisp.jpg` or `465_napa-cabbage.jpg`. Every entry needs a unique photograph, including repeated conventional PLUs. The only reuse exception is an organic entry using its matching conventional product's photo; identify that pairing explicitly for review. Every final organic image must carry the project's standard pink ORGANIC badge in its upper-left corner. Preserve candidate originals without badges here; the badge is not organic certification. Do not use renamed, cropped, resized or recoloured copies to bypass uniqueness.

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

The manually triggered **Fetch unreviewed produce candidates** workflow uses `retrieve_commons.py --review` to search legacy rejected entries, trying known source pages first. Select `scope=working-list-rejected` to search only currently rejected, identity-pinned entries from `current/review-booklets/IMAGE_VISUAL_REVIEW.csv`; set `sequence` to search one entry at a time. For a single sequence, `search_query` can refine the Commons terms without changing the product identity. The workflow refuses stale PickList or WorkingList identities. It accepts supported CC BY and CC BY-SA licences as well as public-domain declarations, but requires creator metadata. Duplicate image content within the package is skipped and later candidates are tried; this includes repeated PLU codes. Its downloadable artifact contains unchanged originals, provenance, contact sheets and an acquisition report for every requested entry. UNRESOLVED means no unique eligible candidate; ERROR means acquisition failed and the workflow fails. Neither a successful download nor a successful run approves an image. Production registers and booklet images remain untouched.
