# Temporary image uploads

Upload candidate replacement photos here before they are reviewed and sorted into the project.

For each photo, use a filename that identifies the rejected entry, such as `009_honeycrisp.jpg` or `465_napa-cabbage.jpg`. If one photo is intended for multiple entries, identify each entry in a companion note.

Include the original source-page URL, creator, licence, and any required attribution for every image. Keep the original file unchanged; do not crop, resize, or approve it here. Images remain candidates until their variety, dimensions, and reuse rights have been checked.

After review, approved images will be moved to their final locations and this temporary folder can be emptied.

For Wikimedia downloads through GitHub Actions, add candidates to `candidates.json` as a JSON array. Each object needs `id` (a unique filename-safe identifier), `plu` (a string), `product`, `image_url` (a direct `https://upload.wikimedia.org/` URL), `source_page_url`, `license` (a suspected licence), and `license_url`. The source and licence URLs must be HTTPS. Example:

```json
[
  {
    "id": "009",
    "plu": "3283",
    "product": "Apples Honey Crisp",
    "image_url": "https://upload.wikimedia.org/example.jpg",
    "source_page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    "license": "CC0 (unverified)",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/"
  }
]
```

Replace the example URLs with actual links; none have been supplied yet. Run `python3 tools/candidate_manifest.py sources/temp_upload/candidates.json --markdown candidates_manifest.md` to generate a review checklist locally. The manually triggered **Fetch unreviewed produce candidates** workflow downloads passing files to a temporary artifact, not into the repository. If any candidate fails or the manifest is empty, the workflow fails; passing files and the checklist remain available in the artifact. It does not follow redirects, so use direct original-file URLs.
