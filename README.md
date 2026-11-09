# Cashier PLU Reference Booklets

Fruit, vegetable, and non-produce cashier references, their audit reports, and the supplied source documents.

## Where to find files

| Folder | Contents |
| --- | --- |
| [current/booklets/](current/booklets/) | Latest fruit, vegetable, and non-produce booklets in editable DOCX and printable PDF formats. |
| [current/reports/](current/reports/) | Latest booklet audit, duplicate-code report, image inventory, and image-match report. |
| [sources/plu/](sources/plu/) | Unmodified authoritative `PickList.xml`. |
| [sources/visual/](sources/visual/) | Supplied visual DOCX inputs, retained unchanged despite their `_CORRECTED` filenames. |
| [archive/provisional/booklets/](archive/provisional/booklets/) | Earlier PDF exports of the supplied visual documents. |
| [archive/provisional/reports/](archive/provisional/reports/) | Earlier provisional spreadsheets, not the current reports. |

## Latest booklets

| Booklet | Editable document | Printable PDF |
| --- | --- | --- |
| Fruit | [DOCX](current/booklets/FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.docx) | [PDF](current/booklets/FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.pdf) |
| Vegetable | [DOCX](current/booklets/VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.docx) | [PDF](current/booklets/VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.pdf) |
| Non-produce | [DOCX](current/booklets/NON_PRODUCE_PLU_CASHIER_BOOKLET.docx) | [PDF](current/booklets/NON_PRODUCE_PLU_CASHIER_BOOKLET.pdf) |

PDFs use landscape US Letter pages. DOCX files are the editable versions; keep each PDF paired with its corresponding DOCX.

## Verification status

**Current means latest, not certified for production use.**

All 597 fruit and vegetable image assignments were visually inspected against their PickList descriptions (see [data/review_notes.txt](data/review_notes.txt)):

| Result | Entries | Booklet status |
| --- | --- | --- |
| Visual match | 446 | ✅ VERIFIED PHOTO (photo source) / 🤖 AI GENERATED REFERENCE IMAGE (AI source) |
| Approximate (variety not distinguishable) | 120 | ⚠ APPROXIMATE PHOTO MATCH / 🤖 |
| Rejected (wrong product/variety, artifacts, bad crop) | 31 | ❌ IMAGE REJECTED – REPLACEMENT NEEDED |

Open problems:

- 31 rejected images still need replacement (for example Napa/Savoy/Suey cabbage showing savoy, White Grapefruit and White Nectarines showing red/yellow flesh, Organic Butternut/Buttercup squash showing lettuce, and images with stray bars or text). Replacement photographs could not be sourced: only GitHub was reachable from the build environment, and Fruits-360 original-size images are below the 500 px minimum.
- 150 images are AI generated (74.9% photographic coverage, below the 90% goal). 595 of 597 images are under 500 px. Many entries share one image (see `Entries Sharing Image` in the audit workbook).
- Image licenses and provenance are not independently established; review before redistributing.
- The non-produce supplement (46 visible PickList records, 45 distinct codes) is a code-and-label reference only; both `77974` entries (Cheese Bun and Pizza Bun) are preserved. Hidden PickList items are not in the booklets.
- A "verified" photo means the image was visually judged to match the product name by a reviewer; it is not a laboratory or supplier-confirmed variety identification.

Regenerate with `python3 tools/extract_entries.py`, edit `data/review_notes.txt`, then `python3 tools/apply_review.py` and re-export the PDFs (`soffice --headless --convert-to pdf`). Requires python-docx, openpyxl and Pillow.

## Sources and reports

[PickList.xml](sources/plu/PickList.xml) is the authority for item codes, English product descriptions, visibility flags, and duplicate investigation. It uses UTF-16 encoding. Preserve code strings, including leading zeros, and do not modify source values to resolve booklet discrepancies.

The final text-only master DOCX files, original visual booklets without `_CORRECTED` suffixes, supporting produce PDFs, and referenced photo assets were not supplied. They are not included in `sources/`.

Current reports:

- [BOOKLET_AUDIT_REPORT.xlsx](current/reports/BOOKLET_AUDIT_REPORT.xlsx): findings, coverage, per-image review results and rejected images.
- [DUPLICATE_PLU_REPORT.csv](current/reports/DUPLICATE_PLU_REPORT.csv): duplicate codes in the fruit and vegetable books.
- [MASTER_IMAGE_LIBRARY.csv](current/reports/MASTER_IMAGE_LIBRARY.csv): entry-to-image assignments and reported sources.
- [IMAGE_MATCH_REPORT.csv](current/reports/IMAGE_MATCH_REPORT.csv): automated match confidence and image-quality notes.

Image paths in the CSV reports point to standalone copies of each booklet image under [data/images/](data/images/); [data/image_review.csv](data/image_review.csv) holds the full per-entry review table.

## Keeping the repository organized

### Replacement image retrieval and checks

Run `python3 tools/retrieve_commons.py --user-agent "PLU-image-review/1.0 (YOUR_CONTACT_URL)"` from the repository root (requires Pillow). It searches Wikimedia Commons for public-domain Honeycrisp apple (3283), Concorde pear (3016), and Savoy cabbage (4555) candidates, requiring at least 500 pixels on **both** sides. Network access to Commons and its upload host is required. No result or a network failure is reported explicitly with a nonzero exit code.

Downloads go to `data/images/candidates/PLU.jpg` (or `.png`), with adjacent `.json` provenance records containing creator, source links, declared licence, dimensions, and candidate status. Existing candidates are never overwritten. Search matches and Commons licence declarations are leads, not proof of variety, photographic origin, or rights ownership. Review the original source page and photograph before approval; icons, illustrations, synthetic images, watermarks, and uncertain varieties remain unacceptable. Nothing is automatically assigned to a booklet or marked approved.

The `verify-images.yml` pull-request workflow checks only added or modified images under `data/images/` and `sources/`, including images whose provenance JSON changes. Existing undersized images do not block unrelated changes. Each new image needs an adjacent `filename.ext.json` record following the downloader's format. Run `python3 tools/verify_images.py path/to/image.jpg` locally. Checks reject corrupt, undersized, multiframe images and missing/invalid provenance fields or unsupported licences; they do **not** establish visual accuracy or independently verify licence claims. Cropped candidates must still meet the 500-pixel minimum and have dimensions updated in their records.

For isolated candidate downloads and a human-review checklist, see [sources/temp_upload/README.md](sources/temp_upload/README.md). Trigger `fetch-candidates.yml` manually on the branch containing the manifest; its artifact is unreviewed and expires after seven days. The workflow never updates production registers.

To opt into the local discovery-stage commit guard, copy `tools/hooks/pre-commit` to the repository's active Git hooks directory as `pre-commit` and make it executable. Check for an existing hook first and merge its behavior rather than overwriting it. The guard blocks staged changes under `current/` or `data/`; explicitly use `ALLOW_REGISTER_UPDATE=1 git commit ...` for authorized updates. Local hooks can be bypassed and do not enforce server-side protection. CODEOWNERS requires valid maintainer identities, and GitHub branch rules must separately require code-owner review and the desired number of approvals.

Put new supplied inputs in `sources/`, latest outputs in `current/`, and superseded outputs in a clearly named version folder under `archive/`. Retain source files unchanged, preserve duplicate records, and regenerate the PDF and related reports whenever a booklet changes. Keep generated documents out of the repository root.
