# Cashier PLU Reference Booklets

Fruit, vegetable, and non-produce cashier references, their audit reports, and the supplied source documents.

## Where to find files

| Folder | Contents |
| --- | --- |
| [current/booklets/](current/booklets/) | Latest fruit, vegetable, and non-produce booklets in editable DOCX and printable PDF formats. |
| [current/review-booklets/](current/review-booklets/) | Standalone review editions in DOCX/PDF/XLSX, with image mapping and validation results; not a production release. |
| [current/review/till-binder-supplier-photos-final/](current/review/till-binder-supplier-photos-final/) | Complete text-only and photo till-binder review copies in XLSX/PDF, Produce previews, standalone booklets, reconciliation and validation reports. |
| [current/reports/](current/reports/) | Latest booklet audit, duplicate-code report, image inventory, and image-match report. |
| [sources/plu/](sources/plu/) | Immutable owner-maintained `PickList.xml` and generated, decision-reviewed `WorkingList.xml`. |
| [sources/binders/](sources/binders/) | Untouched original complete November 2025 binder and its SHA-256 checksum, retained as a reproducible build dependency. |
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

Review-only Excel (`.xlsx`) booklets are provided with the current review files. No output in `current/review-booklets/` is a production release.

Owner-provided duplicate PLU classifications and canonical-name recommendations are recorded in [the review CSV](current/review-booklets/DUPLICATE_PLU_CLASSIFICATIONS.csv) and [the decision summary](current/review-booklets/DUPLICATE_PLU_CLASSIFICATION_REVIEW.md), pinned to exact source identities in `data/working_list_decisions.json`. Applied decisions change only `WorkingList.xml` and review booklets. `PickList.xml` is immutable; every original record and its identity are retained in the reconciliation audit.

## Updating the complete till binder

`tools/build_till_binders.py` creates two **complete copies** of an existing till binder, replacing only its Produce section:

- `Complete Till Binder - Updated - Text Only.xlsx`
- `Complete Till Binder - Updated - Photos.xlsx`

Keep `sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx` unchanged. The owner reuploaded the exact original, verified against SHA-256 `6b0aeaa153233c5f4917811a3f7a5b2212f7a946a0abede372a31db556ab0f63`; it is committed as a build dependency, never reconstructed from outputs. Python runtime dependencies (including transitive packages and PDF inspection) are pinned in `requirements.txt`; all workflows install that manifest. Install dependencies from the repository root with Python 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo apt-get update -qq
sudo apt-get install -y libreoffice-calc libreoffice-writer fonts-dejavu-core fonts-dejavu-extra
```

LibreOffice **Calc and Writer** plus DejaVu fonts are system dependencies, installed locally or by Actions rather than committed as binaries. The checked-in visual DOCX files, AI contact sheets, supplier assets, branding and decision registries supply the remaining build inputs; generation needs no new image downloads.

A tracked-files-only checkout successfully regenerated both complete binders, PDFs, previews and standalone booklets with these dependencies. No uploaded or untracked local assets were needed.

```bash
.venv/bin/python tools/build_till_binders.py \
  --binder sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx \
  --output "/path/to/empty/till-binder-review" \
  --verify-print --booklets
```

The output directory must be empty. Neither the original workbook nor the owner-maintained XML is modified. After a future owner XML upload, repeat the same command with a new empty output directory. Alternatively, the manually triggered **Build till-binder review copies** Actions workflow defaults to the committed original; it fails explicitly if the selected file is missing. Do not upload any different workbook or additional operational/contact information without owner authorization.

Both editions use the same compact three-block layout, WorkingList PLUs and approved cashier-facing names, with organic entries following their confidently identified conventional counterparts and unresolved duplicate PLUs highlighted red. Unknown classifications and ambiguous counterparts are retained and flagged in separate reports. Known non-produce records are excluded from Produce; unrelated operational sheets are never rewritten from the PLU master.

**Cashier entries contain only the PLU, approved WorkingList product name and optional image.** No source, provenance, review or approval labels appear in entries. Organic images retain the requested upper-left pink badge. Audit details stay outside cashier files. Source images are matched by exact WorkingList identity and checksum; merged, renamed or selected identities receive no inherited image approval and remain blank until a candidate passes all production gates. The 48 changed identities have separate visual-suitability decisions in [the image audit](current/review-booklets/IMAGE_VISUAL_REVIEW.csv); those decisions alone do not grant rights, photographic-origin, resolution or production approval. The Murcott, Napa cabbage and strawberries alternates have separate, exact-identity approvals; the other 45 changed entries remain blank. Unchanged identity-linked AI references remain visual references unless explicitly rejected; their provenance and review concerns appear only in external audits. Rejected wrong-product images are never reused.

The original XLSX is **not loaded and resaved** to produce the result. Only the Produce worksheet XML/relationships are replaced; new styles are appended without changing existing style definitions, new image/drawing parts are namespaced, and only Produce print names/content types are added. All original package parts remain present. Validation checks every unrelated original part byte-for-byte, all original styles, unrelated workbook-level settings, internal relationships, worksheet names/order, exact text cells, duplicate warnings, image bytes and image anchors. This preserves unrelated data, formulas, formatting, images, charts, comments, print settings and opaque objects instead of trusting an openpyxl round-trip to preserve unsupported features.

Each binder generation writes `PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt`, `VALIDATION.json`, original-to-WorkingList comparisons, source duplicate associations, excluded-record details, image/placement audits, per-cell/page layout, package-preservation hashes and a full `PICKLIST_SOURCE_RECORDS.xml` audit. Every WorkingList item carries its source identity IDs. Uncertain source changes remain explicit.

`--verify-print` opens/exports the **actual assembled complete workbooks** in Calc and retains **Produce-only PDF previews** in `print-previews/`. It verifies page count and landscape US Letter size, finds every code/description on its planned page, and checks actually drawn image counts. With `--booklets`, the complete binder PDFs are included with the review deliverables, alongside three standalone review booklets in `booklets/` (fruit, vegetable and non-produce), each in DOCX, XLSX and, with `--verify-print`, PDF. Booklet PDF export additionally requires LibreOffice Writer. Booklets show only product names, PLUs and available images; duplicate codes remain red and image metadata stays in the external reports. The non-produce supplement remains code-only.

Complete binder review copies and standalone booklets were regenerated from `WorkingList.xml` using the checksum-verified original. Both complete binder PDFs have 38 pages, including 10 Produce pages with 550 entries; the photo edition embeds the 502 existing identity-linked references plus the approved PLU 4055, 4552 and 4253 alternates, leaving 45 of 48 changed identities blank. Each alternate is approved only for its exact WorkingList identity under owner-confirmed permission; no public reuse licence is claimed. The other changed entries have visual-suitability decisions recorded separately in `current/review-booklets/IMAGE_VISUAL_REVIEW.csv` and `.json`, not rights, photographic-origin, resolution or production approval. All 14 original worksheets and all unrelated OOXML parts, styles and settings are preserved. These checks do not replace a store-printer test. Publication remains blocked by image provenance and approval gates, unresolved supplier confirmation for PLU 94093, and existing classification/reuse gates. Previously published production booklets remain intact. The owner explicitly authorized repository sharing of complete binders and requested committing build dependencies. The convenience ZIP remains excluded.

### Supplied AI contact-sheet references

The owner-supplied AI contact sheets and reviewed crop manifests live in `data/review-references/`. Product-specific crops have their printed labels removed; organic entries receive the standard upper-left pink seal. The latest corrected sheet replaces five previously unsuitable panels (Sing Qua, both acorn squashes, Italian eggplant, and cooking papaya). The owner clarified that PLU 94391 is an organic orange, usually Buck Brand. The **Inspect Buck Brand citrus reference** manual Actions workflow retrieved the supplier infographic from its corrected `/wp-content/` URL and confirmed that the AI panel depicting a mango is unsuitable.

The owner subsequently confirmed permission to use matching supplier images in binders and the repository. `buck-brand.json` maps **13 exact XML identities to 11 original supplier assets**, superseding six AI crop references and six legacy references, and filling 94391 with the correct Mango Orange photograph. Permission evidence, supplier attribution, PDF labels and source checksum are retained outside cashier entries. No public reuse licence or independently verified permission is claimed. Supplier codes never replace store PLUs. Matching conventional Cara Cara and blood-orange images may be reused for their organic counterparts with the pink badge; other conventional entries retain distinct references. Blood-orange and Shaddock cultivar uncertainty remains explicit in the audit. Unmatched varieties are not guessed (for example the PDF's T'orange Lemon is not mapped to an XML orange). The Meyer lemon original is only 470 pixels high and remains below the production size threshold.

The prior review set contained **602 Produce images**, including 114 new AI crops and 13 supplier-photo mappings. The regenerated WorkingList review retains 502 unchanged-identity references and embeds the separately approved PLU 4055, 4552 and 4253 images; 45 other changed identities remain blank. Two supplier mappings also target changed identities and remain held; the remaining supplier mappings retain their owner-confirmed permission evidence. See `current/review-booklets/AI_REFERENCE_REVIEW.csv`, `PHOTO_MAPPING.csv` and `IMAGE_VISUAL_REVIEW.csv`. Organic images keep the standard pink upper-left badge.

`AI_REFERENCE_REVIEW.csv` includes both AI panels (including superseded rejections) and supplier mappings, with exact source identities, checksums and review concerns. `PHOTO_MAPPING.csv` records the actual selected image for each entry. `MISSING_IMAGES.csv` lists the 45 changed WorkingList identities still held blank because their candidate decisions do not clear production gates. `IMAGE_VISUAL_REVIEW.csv` links each user decision to the exact WorkingList/source identities and candidate checksum; alternate-image fetch failures and candidate rejections are documented there. Image presence or visual suitability alone is not production approval. `IMAGE_VISUAL_REVIEW.json` summarizes the review status and unchanged published production outputs.

The manually dispatched **Fetch unreviewed produce candidates** workflow also supports `owner-urls`, which retrieves the exact owner-proposed alternatives listed in `data/review-references/owner-alternate-urls.json` into a temporary Actions artifact. It keeps original files intact and creates a horizontally mirrored basil reference separately. `OWNER_ALTERNATE_FETCH_REPORT.csv` records the latest retrieval: 13 of 14 succeeded, with Murcott blocked by HTTP 403. The artifact expires after seven days; URLs and recorded hashes are not evidence of licence, product identity or production approval.

The user-provided Sobeys Murcott replacement was judged visually suitable and permission was owner-confirmed, but the attached bytes remain unavailable and the source URL returns HTTP 403. A separate Melissa’s image was fetched, visually approved, confirmed by the owner as an actual photograph, and permission-confirmed for repository and cashier-binder use. Its exact checksum, Murcott WorkingList identity and owner-confirmed (not independently documented) permission are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; the creator is not credited by the source and no public reuse licence is asserted. This one asset is approved only for that exact PLU 4055 WorkingList assignment. The exception does not authorize another image or product, and does not clear unrelated publication blockers.

The Foxy Napa cabbage alternate was likewise approved as a photograph for the exact PLU 4552 WorkingList assignment under separately owner-confirmed permission from Foxy or its rights holder. Its source, checksum and permission evidence are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; no public reuse licence or independently verified permission is claimed.

The Koelnmesse-hosted strawberries alternate was approved as a photograph for the exact PLU 4253 WorkingList assignment under separately owner-confirmed permission from the rights holder. Its source, checksum and permission evidence are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; no public reuse licence or independently verified permission is claimed.

The generator verifies source hashes, supplier originals and crop bounds and refuses ambiguous identity reuse. Image approvals are keyed to WorkingList entry IDs. A changed identity receives no old image automatically; AI/supplier manifests flag it for fresh review. These illustrations remain review references, not verified photographs or rights approvals. Supplier photos carry the owner's permission evidence separately, not blanket production approval.

## Updating PickList.xml in the future

**Only @smokydastona updates [sources/plu/PickList.xml](sources/plu/PickList.xml).** It remains the authoritative imported source and is never edited, repaired or normalized by scripts or agents. `tools/working_list.py` recreates `sources/plu/WorkingList.xml` from it and applies decisions in `data/working_list_decisions.json` only when every pinned source identity is an exact match.

The identity is **PLU + exact English description + department + occurrence of an identical record**. On a future upload, matching decisions may be reapplied only to those exact identities. New, changed, visibility-changed or ambiguous records remain source-faithful and are explicitly flagged. If one input identity in a decision group changes or disappears, that group’s decision is not applied. The reconciliation emits `WORKING_LIST_RECONCILIATION.csv`, `WORKING_LIST_ENTRIES.csv`, and `PICKLIST_SOURCE_RECORDS.xml`, preserving every original record and linking its source identity to the resulting WorkingList entry or exclusion.

The **Sync owner PickList** Actions workflow runs on source, decision-registry and pipeline changes. It rebuilds and consumes the WorkingList, keeps PLU values as strings, and includes only visible, non-deleted entries in cashier outputs. It does not automatically transfer image approvals to renamed, merged or selected identities. Changed working identities require a newly reviewed assignment. New or ambiguous products require classification; image search results are leads, not approvals. The workflow stops publication on any unresolved reconciliation, image, rights, classification or reuse blocker and leaves `current/booklets/` untouched.

The existing 46-entry non-produce code-only supplement remains an explicit exception; new entries are **not** silently made code-only. Every produce image needs visual/photographic and rights approval, provenance, a matching checksum and at least 500 pixels on both sides. Rights must have a supported public licence or, only for the exact Murcott, Napa cabbage and strawberries asset checksums and WorkingList identities listed in `tools/verify_images.py`, owner-confirmed permission recorded distinctly from a public licence. Every organic image gets the pink upper-left badge. Photo reuse requires an explicit reviewed `reuse_from_source_id`; organic codes are never inferred or rewritten. Any non-permitted repeated photograph blocks the build.

**Booklet order:** Organic entries do not have a separate organic section. Within each normal produce category, all conventional sizes/duplicate records for a product are grouped together, immediately followed by its organic entries. Description matching ignores the organic label, size words, common plurals and word order; it never changes the printed source values or guesses a match from a PLU. Reviewed `reuse_from_source_id` links also identify counterparts. An optional `placement_after_source_id` in the assignment registry records a reviewed conventional counterpart independently of photo reuse. It must reference an included conventional entry in the same booklet.

Unmatched or ambiguous organic entries stay at the end of their normal produce category, not in an organic section. `BOOKLET_ORDER.csv` records the exact presentation sequence, counterpart IDs and `PLACEMENT_REVIEW_REQUIRED` flags; `organic_placements_needing_review` summarizes those flags without adding a publication blocker. Legacy organic-only section labels are replaced for display using the product family; an unknown family falls back to the booklet's general category and remains flagged. This display categorization does not classify an unassigned XML record or approve any image. The XML catalogue remains in source order; both DOCX rendering and PDF verification use the derived booklet order.

Excel versions follow that same booklet order, with only PLU, product name and optional image on the cashier-facing `Booklet` sheet. The sheet has landscape US Letter print settings and literal text values, preserving leading zeros, duplicates and names beginning with `=`. Provenance, image credits, source identities and decision notes stay in external CSV/XML audit reports, never in cashier-facing sheets.

`data/picklist_assignments.json` is the image/classification review registry, **not an alternate PLU master**. `data/working_list_decisions.json` pins the owner’s product decisions to exact original identities. Removed/hidden assignments and assets remain auditable but do not appear in cashier outputs. Source descriptions and codes are read afresh from `PickList.xml`. Truly identical duplicates have no persistent ID in XML, so their occurrence distinguishes them; adding or removing indistinguishable duplicates requires review. Candidate artwork and XML picture filenames never establish an approved photo.

Local commands (Pillow, python-docx and openpyxl required):

```bash
# Catalogue/review reports only, never publication:
python3 tools/sync_picklist.py --catalog-only --output /tmp/new-picklist-review

# Generate current WorkingList cashier review editions and verify their printed pages:
python3 tools/review_booklets.py --output /tmp/new-working-list-review --pdf

# Build DOCX and Excel only when every required approval passes; output must be empty.
# PDF mode also needs pypdf, LibreOffice Writer and DejaVu Sans fonts:
python3 tools/sync_picklist.py --pdf --output /tmp/new-picklist-build
```

After independently reviewing a candidate's exact product, photographic origin, creator, licence, attribution and any third-party rights, record the approval with:

```bash
python3 tools/approve_picklist_image.py \
  --source-id SOURCE_ID_FROM_PICKLIST_SYNC_CSV \
  --expected-source-sha SHA256_FROM_PICKLIST_SYNC_JSON \
  --candidate /path/to/original.jpg --book Fruit --section Apples \
  --rights-evidence "Source-page and individual rights-review evidence" \
  --approve-visual --verify-photo --verify-rights
```

The candidate needs its adjacent acquisition JSON and exact WorkingList PLU/product association. Run reconciliation first so `WorkingList.xml` is current. Use `--replace` only when intentionally replacing an assignment; for permitted organic reuse also supply `--reuse-from CONVENTIONAL_SOURCE_ID`. This helper copies the unchanged original to `data/images/approved/`, records the checksum and review evidence, updates only the image registry, and refuses stale-source reviews. Commit the new asset and registry; Actions reconciles and retries the gated build. Don't set approval flags without doing the review.

**Owner-only enforcement:** `AGENTS.md` forbids agent edits to XML, `.github/CODEOWNERS` names @smokydastona, and the sync workflow refuses non-owner actors. These are **not a repository write ACL**: enable branch rules requiring pull requests, code-owner approval and the relevant checks, with direct-push/bypass access limited to the owner, and do not give other accounts write access. Protect CODEOWNERS and workflow changes too. This session cannot configure branch protection (GitHub returns 403 for that integration permission); those GitHub settings must be applied by the owner. A failing workflow cannot undo or prevent an already accepted direct push.

Initial reconciliation of the current XML finds **648 visible records**: 643 legacy booklet associations plus **five previously omitted duplicate produce records**, all included in the new catalogue. The old books are not a complete release. The new registry preserves existing verdicts but does not invent missing rights or photographic-origin approval, so the first full build remains blocked until that backlog is reviewed.

## Verification status

**Current means latest, not certified for production use.**

The machine-readable [production-readiness report](current/reports/PRODUCTION_READINESS.json) is **BLOCKED**. [PRODUCTION_BLOCKERS.csv](current/reports/PRODUCTION_BLOCKERS.csv) lists every entry's unresolved visual, image-size, reuse and provenance/rights requirements. Run `python3 tools/audit_production.py` to refresh both; it exits nonzero while any blockers remain. The manually triggered **Audit production readiness** workflow runs the same check and uploads its reports even on failure. Passing automated checks still requires final source, licence, variety and print-layout review; the tool never grants those approvals.

All 597 fruit and vegetable image assignments were visually inspected against their PickList descriptions (see [data/review_notes.txt](data/review_notes.txt)):

| Result | Entries | Booklet status |
| --- | --- | --- |
| Visual match | 446 | ✅ VERIFIED PHOTO (photo source) / 🤖 AI GENERATED REFERENCE IMAGE (AI source) |
| Approximate (variety not distinguishable) | 120 | ⚠ APPROXIMATE PHOTO MATCH / 🤖 |
| Rejected (wrong product/variety, artifacts, bad crop) | 31 | ❌ IMAGE REJECTED – REPLACEMENT NEEDED |

Open problems:

- 31 rejected images still need replacement (for example Napa/Savoy/Suey cabbage showing savoy, White Grapefruit and White Nectarines showing red/yellow flesh, Organic Butternut/Buttercup squash showing lettuce, and images with stray bars or text). Replacement photographs could not be sourced: only GitHub was reachable from the build environment, and Fruits-360 original-size images are below the 500 px minimum.
- 150 images are AI generated (74.9% photographic coverage, below the 90% goal). 595 of 597 images are under 500 px. After allowing matching conventional/organic photo pairs, the uniqueness audit still finds 365 entries in 103 prohibited duplicate-image groups. The existing booklets do not yet meet the unique-image requirement.
- Image licenses and provenance are not independently established; review before redistributing.
- The non-produce supplement (46 visible PickList records, 45 distinct codes) is a code-and-label reference only; both `77974` entries (Cheese Bun and Pizza Bun) are preserved. Hidden PickList items are not in the booklets.
- A "verified" photo means the image was visually judged to match the product name by a reviewer; it is not a laboratory or supplier-confirmed variety identification.

For **legacy booklet image audits only**, use `python3 tools/extract_entries.py`, edit `data/review_notes.txt`, then `python3 tools/apply_review.py` and re-export the PDFs (`soffice --headless --convert-to pdf`). Requires python-docx, openpyxl and Pillow. These legacy commands do not implement PickList updates; use the XML-driven workflow above for those. `apply_review.py` refuses to write booklets or reports while prohibited image reuse or missing organic watermarks remain; existing visual-match verdicts do not satisfy uniqueness.

### Unique image requirement

Every fruit and vegetable booklet entry must have its own unique image, including repeated conventional PLU codes, with one exception: an organic entry may reuse its matching conventional product's photo with the standard pink **ORGANIC** identification badge in the **upper-left corner**. Every organic image needs that same badge style and placement, even if its photograph is otherwise unique. Organic status comes from the PickList name/category/section, not from guessing based on the code.

The automated reuse exception requires the same underlying photograph, the same booklet and the exact code pairing `organic PLU = "9" + conventional PLU`. It never pairs unrelated products or strips leading zeros. Entries without an identifiable conventional counterpart still need their own photograph; they receive the pink label but no reuse exception. More than one conventional entry sharing a photo remains prohibited.

All **206 organic entries** now have the pink badge in the standalone images and paired DOCX/PDF booklets. The source artwork is [data/branding/Organic_Pink_Leaf_Seal.png](data/branding/Organic_Pink_Leaf_Seal.png), and the normalized transparency-safe version used by the renderer is [data/branding/pink-organic-badge.png](data/branding/pink-organic-badge.png). `badge_artwork()` removes only edge-connected white background so the sticker sits over the photo without a square white block. Each badge is 30% of the image's shortest side, inset 2.5% from the top and left (with minimum sizes for legibility). `data/organic_watermarks.json` records unchanged originals inside the supplied visual DOCX files, the watermark version and exact badge checksum. Regeneration refuses altered images or badge records instead of silently restoring them. The badge is an entry-identification aid, **not organic certification or image approval**; existing rejected/approximate verdicts and unresolved rights remain unchanged.

`python3 tools/organic_watermarks.py --check` verifies the artwork, every badge and that every DOCX image matches its standalone assignment. `python3 tools/organic_watermarks.py` reapplies the standard badge from those originals, updates image paths and the audit workbook, and preserves review verdicts; re-export both produce PDFs afterward. New replacement photographs need their own reviewed provenance and recorded derivation before assignment; this legacy-source renderer deliberately refuses unrecorded originals. PDF export requires DejaVu Sans fonts to preserve pagination. For lossless badges, use `soffice --headless --convert-to 'pdf:writer_pdf_Export:{"UseLosslessCompression":{"type":"boolean","value":"true"},"ReduceImageResolution":{"type":"boolean","value":"false"}}' --outdir current/booklets current/booklets/*_PRODUCTION.docx`.

Run `python3 tools/check_image_uniqueness.py --report current/reports/DUPLICATE_IMAGE_REPORT.csv` to audit all entry assignments in `data/entries.csv`. It exits nonzero for prohibited reuse, missing/altered organic watermarks, or missing/unreadable images. The [duplicate-image report](current/reports/DUPLICATE_IMAGE_REPORT.csv) lists every entry in prohibited groups, preserving repeated codes and leading zeros; permitted conventional/organic pairs are excluded.

Automated comparison uses decoded, EXIF-oriented pixels and compares organic images to their recorded **unwatermarked originals** so that the badge cannot hide unrelated reuse. Different filenames, metadata, lossless formats, crops, resizing or colour adjustments do not create a new photograph. Visual review must additionally reject re-encoded, resized, cropped or otherwise altered copies; the automated check does not prove that photographs are visually distinct. Source documents remain unchanged; non-produce entries currently have no images.

## Sources and reports

[PickList.xml](sources/plu/PickList.xml) is the authority for item codes, English product descriptions, visibility flags, and duplicate investigation. It uses UTF-16 encoding. Preserve code strings, including leading zeros, and do not modify source values to resolve booklet discrepancies.

The final text-only master DOCX files, original visual booklets without `_CORRECTED` suffixes, supporting produce PDFs, and referenced photo assets were not supplied. They are not included in `sources/`.

Current reports:

- [BOOKLET_AUDIT_REPORT.xlsx](current/reports/BOOKLET_AUDIT_REPORT.xlsx): findings, coverage, per-image review results and rejected images.
- [DUPLICATE_PLU_REPORT.csv](current/reports/DUPLICATE_PLU_REPORT.csv): duplicate codes in the fruit and vegetable books.
- [DUPLICATE_IMAGE_REPORT.csv](current/reports/DUPLICATE_IMAGE_REPORT.csv): entries sharing identical image content, independent of PLU-code duplication.
- [PRODUCTION_BLOCKERS.csv](current/reports/PRODUCTION_BLOCKERS.csv) and [PRODUCTION_READINESS.json](current/reports/PRODUCTION_READINESS.json): per-entry release blockers and counts measured from current files.
- [PICKLIST_CATALOG.csv](current/reports/PICKLIST_CATALOG.csv), [PICKLIST_SYNC.csv](current/reports/PICKLIST_SYNC.csv) and [PICKLIST_SYNC.json](current/reports/PICKLIST_SYNC.json): full XML catalogue and authoritative reconciliation, including records omitted by legacy books.
- [IMAGE_REQUESTS.csv](current/reports/IMAGE_REQUESTS.csv): new/unassigned records needing candidate image discovery; [INACTIVE_ASSIGNMENTS.csv](current/reports/INACTIVE_ASSIGNMENTS.csv): removed/hidden/replaced associations retained for review.
- [MASTER_IMAGE_LIBRARY.csv](current/reports/MASTER_IMAGE_LIBRARY.csv): entry-to-image assignments and reported sources.
- [IMAGE_MATCH_REPORT.csv](current/reports/IMAGE_MATCH_REPORT.csv): automated match confidence and image-quality notes.

Image paths in the CSV reports point to standalone copies of each booklet image under [data/images/](data/images/); [data/image_review.csv](data/image_review.csv) holds the full per-entry review table.

## Keeping the repository organized

### Replacement image retrieval and checks

Accepted image licence types are CC0 1.0; CC BY 2.0, 3.0 and 4.0; CC BY-SA 2.0, 3.0 and 4.0; and individually verified public-domain works. Photographs need not be MIT-licensed. An accepted licence type is not individual rights clearance: verify the source declaration, creator (or documented anonymous authorship), licence version, and any third-party rights before use. A Public Domain Mark is not a licence or proof of public-domain status; record the actual basis for the claim.

CC BY and CC BY-SA require the applicable creator credit, source and licence information, and identification of changes as required by that version. Share-alike applies to adaptations of the photograph, not automatically to independent booklet material merely collected alongside it. Keep photo licensing distinct from the repository's software licence. Record any crop, background removal or other modification and comply with the applicable adaptation terms. CC0 and verified public-domain works have no copyright attribution requirement, but this project still preserves provenance.

Run `python3 tools/retrieve_commons.py --review data/image_review.csv --leads sources/temp_upload/candidates.json --output /tmp/produce-review --user-agent "PLU-image-review/1.0 (YOUR_CONTACT_URL)"` from the repository root (requires Pillow). It searches Wikimedia Commons separately for all 31 rejected entries using explicit variety-specific queries, trying known source pages first. Duplicate PLUs and organic entries stay separate. It accepts the supported licence declarations as acquisition leads, requiring creator information and at least 500 pixels on **both** sides. Generic or uncertain matches must still be rejected during review. The legacy command without `--review` searches only three products, using the same accepted licence types.

The package output directory must be empty. It contains unchanged originals with per-image provenance JSON (creator, source-page and original-file URLs, declared licence, attribution, dimensions, checksum and raw Commons metadata), a combined `provenance.json`, labelled contact sheets, and an `acquisition-report.csv` covering every rejected entry. Up to two candidates are retained per entry (`--per-entry 1..5`). Missing metadata, unsupported licences and undersized files are not admitted. Unsafe oversized or unreadable images are skipped and recorded in the report; acquisition continues with later candidates. Duplicate image content within a package is skipped, including across repeated PLUs; acquisition tries later candidates and leaves an entry UNRESOLVED if no unique eligible candidate remains. This is not a comparison against every historical or production photograph. No-result entries are explicitly UNRESOLVED; network errors fail the run while preserving its partial review package. Network access to Commons and its upload host is required.

Every new package also includes `license-register.csv`: one row per candidate/entry association with filename, PLU, original and source-page URLs, creator, declared licence/version/link, conditional commercial-use and modification permissions, attribution, share-alike, permission notes, and separate rights-verification and visual-approval statuses. These start as `NOT_VERIFIED` and `NOT_APPROVED`; licence eligibility never changes production verdicts. The attribution column is a draft from captured metadata, not a substitute for checking source-specific credit requirements. Public-domain permissions remain `UNVERIFIED` until the claim is substantiated. Preserve raw provenance alongside the CSV.

[data/candidate_license_register.csv](data/candidate_license_register.csv) records the 51 associations from acquisition run [42553673620](https://github.com/smokydastona/produce-plu-code-book/actions/runs/42553673620), not 51 unique photographs or approved images. To generate a fresh register from an existing package, run `python3 tools/license_register.py /path/to/provenance.json --output /path/to/new-license-register.csv`. This initializes unverified statuses and refuses to overwrite an existing register, preserving manual review work.

Search matches and Commons licence declarations are leads, not proof of variety, photographic origin, organic certification, or rights ownership. Review the original source page and photograph before approval; icons, illustrations, synthetic images, third-party watermarks, and uncertain varieties remain unacceptable. The project's own standard pink ORGANIC identification label is the only permitted watermark. Nothing is automatically assigned to a booklet or marked approved. No production register is modified by acquisition.

The `verify-images.yml` workflow runs on pull requests and pushes to `main`. It checks added or modified images under `data/images/` and `sources/`, including images whose provenance JSON changes. Checked images are compared against all standalone images in those folders and each other. Assignment changes are also compared against the base commit: newly introduced prohibited sharing or missing/altered organic labels fail. Unchanged legacy duplicate groups are warned about, not approved; full compliance still requires the separate uniqueness and production-readiness audits to pass.

Each new photograph needs an adjacent `filename.ext.json` record following the downloader's format. Run `python3 tools/verify_images.py path/to/image.jpg` locally for candidate checks. The workflow makes a narrow exception for exact, verified standard-watermark-only updates to previously assigned legacy images: it proves the original was already assigned to that entry in the base commit and warns that existing size/licence/review problems remain. It does not grandfather new photographs. Checks otherwise reject corrupt, undersized, multiframe images, missing/invalid provenance and unsupported licences; they do **not** establish visual accuracy or independently verify licence claims. Cropped candidates must still meet the 500-pixel minimum and have dimensions updated in their records.

For isolated candidate downloads and a human-review checklist, see [sources/temp_upload/README.md](sources/temp_upload/README.md). Trigger `fetch-candidates.yml` manually with `scope=rejected` to acquire all rejected entries and download the `unreviewed-produce-images-0` ZIP artifact; it includes contact sheets, originals, provenance and unresolved/error results, and expires after seven days. The workflow never updates production registers.

For the full production backlog, select `scope=all` in that workflow and choose `per_entry=1..5`. It derives `ALL_IMAGE_REQUESTS.csv` from the current XML, including unassigned products and excluding only explicitly reviewed code-only entries. Six non-overlapping entry shards run with at most two concurrent jobs on GitHub-hosted runners, where Commons is reachable. Select a numbered `shard` to rerun only that shard. Each shard uploads `unreviewed-produce-images-N` (originals) and `candidate-review-metadata-N` (small provenance/register/report/contact-sheet package). Locally, first run `python3 tools/sync_picklist.py --catalog-only --output /tmp/picklist-sync`, then pass `--review /tmp/picklist-sync/ALL_IMAGE_REQUESTS.csv --all-entries --shard-count 6 --shard-index 0` to the retrieval command and repeat indices 0 through 5 in separate empty output directories, without the legacy `--leads` argument. XML-derived requests use the product description, not legacy index-based queries or leads. Search requires the product terms, not an exact phrase. Every query and result is recorded. Cross-shard image reuse must still be reviewed, and no search result is automatically a production image or rights approval.

The workflow also runs `tools/probe_image_sources.py` on the GitHub-hosted runner to check the alternative library addresses, request discovery searches for entries #361, #368, #370 and #433, and retrieve the Fruits-360 original-size file tree. Its separate `source-discovery` artifact preserves responses and a per-request CSV, including network failures. HTTP success does not establish that a site honored the search query, returned photos, or grants reuse rights. Failed probes produce a workflow warning without preventing Commons acquisition. These probes do not download or approve alternative-source images.

To opt into the local discovery-stage commit guard, copy `tools/hooks/pre-commit` to the repository's active Git hooks directory as `pre-commit` and make it executable. Check for an existing hook first and merge its behavior rather than overwriting it. The guard blocks staged changes under `current/` or `data/`; explicitly use `ALLOW_REGISTER_UPDATE=1 git commit ...` for authorized updates. Local hooks can be bypassed and do not enforce server-side protection. CODEOWNERS requires valid maintainer identities, and GitHub branch rules must separately require code-owner review and the desired number of approvals.

Put new supplied inputs in `sources/`, latest outputs in `current/`, and superseded outputs in a clearly named version folder under `archive/`. Retain source files unchanged, preserve duplicate records, and regenerate the PDF and related reports whenever a booklet changes. Keep generated documents out of the repository root.
