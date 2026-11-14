# Cashier PLU Reference Booklets

Fruit, vegetable, and non-produce cashier references, their audit reports, and the supplied source documents.

## Where to find files

| Folder | Contents |
| --- | --- |
| [outputs/booklets/](outputs/booklets/) | Last published fruit, vegetable, and non-produce booklets, retained while publication is blocked. |
| [outputs/review-booklets/](outputs/review-booklets/) | Retained identity-pinned review decisions and audit evidence; no standalone review booklets. |
| [outputs/till-binder-review/](outputs/till-binder-review/) | Latest complete till-binder review workbook and PDF, plus validation reports. |
| [outputs/reports/](outputs/reports/) | Latest booklet audit, duplicate-code report, image inventory, and image-match report. |
| [sources/plu/](sources/plu/) | Immutable owner-maintained `PickList.xml` and generated, decision-reviewed `WorkingList.xml`. |
| [sources/image-library/](sources/image-library/) | Single local JPEG library for approved, review and legacy images, with separate approval and usage indexes and provenance sidecars. |
| [sources/binders/](sources/binders/) | Untouched original complete November 2025 binder and its SHA-256 checksum, retained as a reproducible build dependency. |
| [sources/visual/](sources/visual/) | Supplied visual DOCX inputs, retained unchanged despite their `_CORRECTED` filenames. |
| [archive/provisional/booklets/](archive/provisional/booklets/) | Earlier PDF exports of the supplied visual documents. |
| [archive/provisional/reports/](archive/provisional/reports/) | Earlier provisional spreadsheets, not the current reports. |

## Last published booklets

| Booklet | Editable document | Printable PDF |
| --- | --- | --- |
| Fruit | [DOCX](outputs/booklets/FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.docx) | [PDF](outputs/booklets/FRUIT_VISUAL_PLU_BOOKLET_PRODUCTION.pdf) |
| Vegetable | [DOCX](outputs/booklets/VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.docx) | [PDF](outputs/booklets/VEGETABLE_VISUAL_PLU_BOOKLET_PRODUCTION.pdf) |
| Non-produce | [DOCX](outputs/booklets/NON_PRODUCE_PLU_CASHIER_BOOKLET.docx) | [PDF](outputs/booklets/NON_PRODUCE_PLU_CASHIER_BOOKLET.pdf) |

PDFs use landscape US Letter pages. DOCX files are the editable versions; keep each PDF paired with its corresponding DOCX.

The last published booklets remain intact while the updated binder awaits production approval. Review evidence is not a production release.

Owner-provided duplicate PLU classifications and canonical-name recommendations are recorded in [the review CSV](outputs/review-booklets/DUPLICATE_PLU_CLASSIFICATIONS.csv) and [the decision summary](outputs/review-booklets/DUPLICATE_PLU_CLASSIFICATION_REVIEW.md), pinned to exact source identities in `data/working_list_decisions.json`. Applied decisions change only `WorkingList.xml` and review booklets. `PickList.xml` is immutable; every original record and its identity are retained in the reconciliation audit.

## Updating the complete till binder

`tools/build_till_binders.py` creates one photo-inclusive **complete binder**, replacing its Produce and Deli sections and combining the four Bulk sheets. The editable workbook is `Complete Till Binder - Updated - Photos.xlsx`; `--verify-print` also supplies a PDF of that same binder, not a second edition.

Keep `sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx` unchanged. The owner reuploaded the exact original, verified against SHA-256 `6b0aeaa153233c5f4917811a3f7a5b2212f7a946a0abede372a31db556ab0f63`; it is committed as a build dependency, never reconstructed from outputs. Python runtime dependencies (including transitive packages and PDF inspection) are pinned in `requirements.txt`; all workflows install that manifest. Install dependencies from the repository root with Python 3.12:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo apt-get update -qq
sudo apt-get install -y libreoffice-calc libreoffice-writer fonts-dejavu-core fonts-dejavu-extra
```

LibreOffice **Calc and Writer** plus DejaVu fonts are system dependencies, installed locally or by Actions rather than committed as binaries. The checked-in visual DOCX files, AI contact sheets, supplier assets, branding and decision registries supply the remaining build inputs; generation needs no new image downloads.

The checked-in sources are sufficient to generate the complete binder without additional image downloads.

```bash
.venv/bin/python tools/build_till_binders.py \
  --binder sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx \
  --output "/path/to/empty/till-binder-review" \
  --verify-print
```

The output directory must be empty. Neither the input workbook nor the owner-maintained XML is modified. After a future owner XML upload, repeat the command with a new empty output directory. The manually triggered **Build complete till-binder review** workflow defaults to the committed original and accepts a repository-relative binder template path. Future owner edits to other sheets can be supplied in an updated complete binder template; the build preserves those sheets, replaces Produce and Deli from their respective sources, and combines the four original Bulk sheets if present. Do not upload any different workbook or additional operational/contact information without owner authorization.

Bulk uses one worksheet with six landscape US Letter pages, three Product/PLU lists per page, green headers, pale-green category bands and subtle row borders matching the Produce/Deli theme. Product names and bold text PLUs print at 11 pt with 100% scaling. Pages group Candy; Chocolate/Yogurt and Snacking Nuts/Seeds; Baking and Nut Mixes; Organics; the four seasonal categories; and Dried Fruit, Mealtime and Wrapped Candy/Chocolate. Column splits balance wrapped-text heights and repeat category headings, keeping each heading with its entries. All 400 original entries retain their exact names and code strings, including duplicates and `DC` codes. `BULK_LAYOUT.csv` records the source cells and new page/cell mapping. Future builds apply this same layout to both the original four-sheet template and already-combined templates. Unsupported features, changed categories, unprinted data or groups that no longer fit are reported instead of silently dropped or shrunk.

The owner-uploaded updated deli guide is preserved unchanged at `sources/binders/Deli.docx`. Its adjusted Word version, `Updated_Deli_Two_Columns.docx`, uses two flowing columns; `Updated_Deli_Two_Columns.xlsx` uses two side-by-side Product/PLU lists, retaining all 52 entries and 10 category headings in source order. Every complete binder build replaces the existing Deli worksheet from this Excel source. The builder verifies its contents and layout against the original deli document, preserves PLUs as text, and fails on missing or stale sources. `DELI_LAYOUT.csv` and `VALIDATION.json` record the exact cells, counts and source checksum. Deli does not use or alter the produce XML. To prepare a future owner-supplied revision, run `tools/build_deli_sheet.py NEW_DELI.docx --output /path/to/empty/source-folder`, then replace the three deli source files together after reviewing the conversion.

The current review binder is saved in `outputs/till-binder-review/`. It is not a production release; production publication remains blocked and published booklets are unchanged.

The Produce sheet uses a compact three-block layout, WorkingList PLUs and approved cashier-facing names, with organic entries following their confidently identified conventional counterparts and unresolved duplicate PLUs highlighted red. Unknown classifications and ambiguous counterparts are retained and flagged in separate reports. Known non-produce records are excluded from Produce; unrelated operational sheets are never rewritten from the PLU master.

**Cashier entries contain only the PLU, approved WorkingList product name and optional image.** No source, provenance, review or approval labels appear in entries. Organic images retain the requested upper-left pink badge. Audit details stay outside cashier files. Source images are matched by exact WorkingList identity and checksum; merged, renamed or selected identities receive no inherited image approval and remain blank until a candidate passes all production gates. The 48 changed identities have separate visual-suitability decisions in [the image audit](outputs/review-booklets/IMAGE_VISUAL_REVIEW.csv); those decisions alone do not grant rights, photographic-origin, resolution or production approval. Fourteen images have separate, exact-identity approvals; the other 34 changed entries remain blank. Unchanged identity-linked AI references remain visual references unless explicitly rejected; their provenance and review concerns appear only in external audits. Rejected wrong-product images are never reused.

The original XLSX is **not loaded and resaved** to produce the result. Produce, Deli and Bulk worksheet XML/relationships are replaced and workbook metadata is adjusted for the Bulk merge; new styles are appended without changing existing style definitions, new image/drawing parts are namespaced, and print names/content types are updated. All original package parts remain present. The photo edition embeds generated copies, downsampled to at most 192 x 120 px (four times the image-cell box), as quality-90 JPEG for opaque images and optimized PNG where transparency is present; original image assets are unchanged. The builder checks that the photo workbook stays below GitHub's 100 MiB file limit. Validation checks every unrelated original part byte-for-byte, all original styles, unrelated workbook-level settings, internal relationships, worksheet names/order, exact text cells, duplicate warnings, embedded image bytes and image anchors. This preserves unrelated data, formulas, formatting, images, charts, comments, print settings and opaque objects instead of trusting an openpyxl round-trip to preserve unsupported features.

Each binder generation writes `PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt`, `VALIDATION.json`, original-to-WorkingList comparisons, source duplicate associations, excluded-record details, image/placement audits, per-cell/page layout, package-preservation hashes and a full `PICKLIST_SOURCE_RECORDS.xml` audit. Every WorkingList item carries its source identity IDs. Uncertain source changes remain explicit.

`--verify-print` opens and exports the **actual assembled complete workbook** in Calc as one complete binder PDF. It verifies Produce page count and landscape US Letter size, finds every code/description on its planned page, and checks actually drawn image counts. Deli must print on one portrait US Letter page with every owner-supplied product and PLU present. Bulk must print on six consecutive landscape US Letter pages with all names and PLUs on their intended pages and printed PLU fonts at 11 pt. No separate sheet PDFs or booklets are generated by the binder workflow. Standalone booklet generation remains a separate process.

The binder has 11 worksheets after combining Bulk and retains unrelated OOXML parts, styles and settings. Automated checks do not replace a store-printer test. Publication remains blocked by reconciliation, image and reuse gates; previously published production booklets remain intact.

### Supplied AI contact-sheet references

The owner-supplied AI contact sheets and reviewed crop manifests live in `data/review-references/`. Product-specific crops have their printed labels removed; organic entries receive the standard upper-left pink seal. The latest corrected sheet replaces five previously unsuitable panels (Sing Qua, both acorn squashes, Italian eggplant, and cooking papaya). The owner clarified that PLU 94391 is an organic orange, usually Buck Brand. The **Inspect Buck Brand citrus reference** manual Actions workflow retrieved the supplier infographic from its corrected `/wp-content/` URL and confirmed that the AI panel depicting a mango is unsuitable.

The owner subsequently confirmed permission to use matching supplier images in binders and the repository. `buck-brand.json` maps **13 exact XML identities to 11 original supplier assets**, superseding six AI crop references and six legacy references, and filling 94391 with the correct Mango Orange photograph. Permission evidence, supplier attribution, PDF labels and source checksum are retained outside cashier entries. No public reuse licence or independently verified permission is claimed. Supplier codes never replace store PLUs. Matching conventional Cara Cara and blood-orange images may be reused for their organic counterparts with the pink badge; other conventional entries retain distinct references. Blood-orange and Shaddock cultivar uncertainty remains explicit in the audit. Unmatched varieties are not guessed (for example the PDF's T'orange Lemon is not mapped to an XML orange). The Meyer lemon original is only 470 pixels high and remains below the production size threshold.

The prior review set contained **602 Produce images**, including 114 new AI crops and 13 supplier-photo mappings. The regenerated WorkingList review embeds 516 images: 502 unchanged-identity references and 14 separately approved changed-identity images. The remaining 34 changed identities are blank. Twelve of the 13 Buck Brand assignments now have exact-identity image approvals; the Meyer lemon supplier reference remains unapproved because its original is below the size threshold. See `outputs/review-booklets/AI_REFERENCE_REVIEW.csv`, `PHOTO_MAPPING.csv` and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`. Organic images keep the standard pink upper-left badge.

`AI_REFERENCE_REVIEW.csv` includes both AI panels (including superseded rejections) and supplier mappings, with exact source identities, checksums and review concerns. `PHOTO_MAPPING.csv` records the actual selected image for each entry. `MISSING_IMAGES.csv` lists the 34 changed WorkingList identities still held blank because their candidate decisions do not clear production gates. `IMAGE_VISUAL_REVIEW.csv` links the initial visual decisions to the exact WorkingList/source identities and candidate checksum; subsequent separate approvals and blockers are in `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`. Image presence or visual suitability alone is not production approval. `IMAGE_VISUAL_REVIEW.json` summarizes the initial visual review and unchanged published production outputs.

The manually dispatched **Fetch unreviewed produce candidates** workflow also supports `owner-urls`, which retrieves the exact owner-proposed alternatives listed in `data/review-references/owner-alternate-urls.json` into a temporary Actions artifact. It keeps original files intact and creates a horizontally mirrored basil reference separately. `OWNER_ALTERNATE_FETCH_REPORT.csv` records the latest retrieval: 13 of 14 succeeded, with Murcott blocked by HTTP 403. The artifact expires after seven days; URLs and recorded hashes are not evidence of licence, product identity or production approval.

The user-provided Sobeys Murcott replacement was judged visually suitable and permission was owner-confirmed, but the attached bytes remain unavailable and the source URL returns HTTP 403. A separate Melissa’s image was fetched, visually approved, confirmed by the owner as an actual photograph, and permission-confirmed for repository and cashier-binder use. Its exact checksum, Murcott WorkingList identity and owner-confirmed (not independently documented) permission are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; the creator is not credited by the source and no public reuse licence is asserted. This one asset is approved only for that exact PLU 4055 WorkingList assignment. The exception does not authorize another image or product, and does not clear unrelated publication blockers.

The Foxy Napa cabbage alternate was likewise approved as a photograph for the exact PLU 4552 WorkingList assignment under separately owner-confirmed permission from Foxy or its rights holder. Its source, checksum and permission evidence are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; no public reuse licence or independently verified permission is claimed.

The Koelnmesse-hosted strawberries alternate was approved as a photograph for the exact PLU 4253 WorkingList assignment under separately owner-confirmed permission from the rights holder. Its source, checksum and permission evidence are recorded in the sidecar and `IMAGE_VISUAL_REVIEW_SUPPLEMENTS.csv`; no public reuse licence or independently verified permission is claimed.

The owner-provided basil alternate was horizontally mirrored at the owner's request and approved as a photograph for exact PLU 4885 under separately owner-confirmed permission to use and mirror it. The original, mirrored image, checksums and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The owner-provided cilantro alternate was approved as a photograph for exact PLU 4889 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The higher-resolution seedless tangerine alternate was approved as a photograph for exact PLU 4458 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed. The smaller initially reviewed image did not meet the minimum resolution.

The white creamer potato alternate was approved as a photograph for exact PLU 4724 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The higher-resolution red creamer potato alternate was approved as a photograph for exact PLU 4723 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed. The smaller initially reviewed image did not meet the minimum resolution.

The higher-resolution sweet potato alternate was approved as a photograph for exact PLU 4074 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed. The smaller initially reviewed image did not meet the minimum resolution.

The Warba potato alternate was approved as a photograph for exact PLU 60271 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The Opo squash alternate was approved as a photograph for exact PLU 3141 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The orange granadilla alternate was approved as a photograph for exact PLU 3038 under separately owner-confirmed permission for the public repository and cashier binders. Its checksum and evidence are retained in `data/review-references/owner-alternates/`; no public reuse licence or independently verified permission is claimed.

The supplier Cara Cara photo was separately approved for the exact PLU 3110 and 93110 WorkingList entries under the existing owner-confirmed supplier permission and explicit organic reuse decision. The original JPEG is retained; a lossless PNG rendering is used where needed for DOCX compatibility.

The generator verifies source hashes, supplier originals and crop bounds and refuses ambiguous identity reuse. Image approvals are keyed to WorkingList entry IDs. A changed identity receives no old image automatically; AI/supplier manifests flag it for fresh review. These illustrations remain review references, not verified photographs or rights approvals. Supplier photos carry the owner's permission evidence separately, not blanket production approval.

## Updating PickList.xml in the future

**Only @smokydastona updates [sources/plu/PickList.xml](sources/plu/PickList.xml).** It remains the authoritative imported source and is never edited, repaired or normalized by scripts or agents. `tools/working_list.py` recreates `sources/plu/WorkingList.xml` from it and applies decisions in `data/working_list_decisions.json` only when every pinned source identity is an exact match.

The identity is **PLU + exact English description + department + occurrence of an identical record**. On a future upload, matching decisions may be reapplied only to those exact identities. New, changed, visibility-changed or ambiguous records remain source-faithful and are explicitly flagged. If one input identity in a decision group changes or disappears, that group’s decision is not applied. The reconciliation emits `WORKING_LIST_RECONCILIATION.csv`, `WORKING_LIST_ENTRIES.csv`, and `PICKLIST_SOURCE_RECORDS.xml`, preserving every original record and linking its source identity to the resulting WorkingList entry or exclusion.

The **Sync owner PickList** Actions workflow runs on source, decision-registry and pipeline changes. It rebuilds and consumes the WorkingList, keeps PLU values as strings, and includes only visible, non-deleted entries in cashier outputs. It does not automatically transfer image approvals to renamed, merged or selected identities. Changed working identities require a newly reviewed assignment. New or ambiguous products require classification; image search results are leads, not approvals. The workflow stops publication on any unresolved reconciliation, image, rights, classification or reuse blocker and leaves `outputs/booklets/` untouched.

The existing 46-entry non-produce code-only supplement remains an explicit exception; new entries are **not** silently made code-only. Every produce image needs visual/photographic and rights approval, provenance, a matching checksum and at least 500 pixels on both sides. Rights must have a supported public licence or, only for the exact asset checksums and WorkingList identities listed in `tools/verify_images.py`, owner-confirmed permission recorded distinctly from a public licence. Every organic image gets the pink upper-left badge. Photo reuse requires an explicit reviewed `reuse_from_source_id` and matching normalized product descriptions, ignoring organic and size words, common plurals and word order. Names that do not match require a reviewed WorkingList product decision before reuse; PLUs are never inferred or rewritten. Any non-permitted repeated photograph blocks the build.

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

The current PickList has 724 source records, including 648 visible records before WorkingList decisions. The generated WorkingList has 672 records; 596 are visible, 48 are merged or standardized, and two require owner review. The legacy booklets contain 643 associations plus five previously omitted duplicate produce records, but are not a complete release. The image registry preserves existing verdicts but does not invent missing rights or photographic-origin approval, so publication remains blocked until reconciliation and image review pass.

## Verification status

**Current means latest, not certified for production use.**

The machine-readable [production-readiness report](outputs/reports/PRODUCTION_READINESS.json) is **BLOCKED**. Run `python3 tools/audit_production.py` to refresh the authoritative PickList reconciliation and identity-matched image-approval reports. `PICKLIST_SYNC.csv` and the WorkingList reconciliation reports identify blockers, including unresolved hidden or deleted source records and decisions; the command exits nonzero while current production is blocked. The manually triggered **Audit production readiness** workflow uploads only reports produced by that run. Passing automated checks still requires final source, licence, variety and print-layout review; the tool never grants those approvals.

The legacy booklets are audited independently: `python3 tools/audit_production.py --legacy` also refreshes [PRODUCTION_BLOCKERS.csv](outputs/reports/PRODUCTION_BLOCKERS.csv) and records the historical image audit under `legacy_image_audit`. Legacy blockers do not prevent a new, fully reviewed WorkingList build.

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

For **legacy booklet image audits only**, use `python3 tools/extract_entries.py`, edit `data/review_notes.txt`, then `python3 tools/apply_review.py` and re-export the PDFs (`soffice --headless --convert-to pdf`). Requires python-docx, openpyxl and Pillow. The generated booklet status treats every legacy entry as pre-approved while `data/image_review.csv` and reports retain the historical verdict, notes and provenance. These legacy commands do not implement PickList updates; use the XML-driven workflow above for those. `apply_review.py` refuses to write booklets or reports while prohibited image reuse or missing organic watermarks remain; legacy image approval does not grant uniqueness exceptions.

### Unique image requirement

Every fruit and vegetable booklet entry must have its own unique image, including repeated conventional PLU codes, with one exception: an organic entry may reuse its matching conventional product's photo with the standard pink **ORGANIC** identification badge in the **upper-left corner**. Every organic image needs that same badge style and placement, even if its photograph is otherwise unique. Organic status comes from the PickList name/category/section, not from guessing based on the code.

The legacy image audit requires the same underlying photograph, the same booklet and the exact code pairing `organic PLU = "9" + conventional PLU`. The current WorkingList gate instead requires a reviewed counterpart link and matching normalized product descriptions, without inferring or rewriting PLUs. Entries without an identifiable conventional counterpart still need their own photograph; they receive the pink label but no reuse exception. More than one conventional entry sharing a photo remains prohibited.

All **206 organic entries** now have the pink badge in the standalone images and paired DOCX/PDF booklets. The source artwork is [data/branding/Organic_Pink_Leaf_Seal.png](data/branding/Organic_Pink_Leaf_Seal.png), and the normalized transparency-safe version used by the renderer is [data/branding/pink-organic-badge.png](data/branding/pink-organic-badge.png). `badge_artwork()` removes only edge-connected white background so the sticker sits over the photo without a square white block. Each badge is 30% of the image's shortest side, inset 2.5% from the top and left (with minimum sizes for legibility). `data/organic_watermarks.json` records unchanged originals inside the supplied visual DOCX files, the watermark version and exact badge checksum. Regeneration refuses altered images or badge records instead of silently restoring them. The badge is an entry-identification aid, **not organic certification or image approval**; existing rejected/approximate verdicts and unresolved rights remain unchanged.

`python3 tools/organic_watermarks.py --check` verifies the artwork, every badge and that every DOCX image matches its standalone assignment. `python3 tools/organic_watermarks.py` reapplies the standard badge from those originals, updates image paths and the audit workbook, and preserves review verdicts; re-export both produce PDFs afterward. New replacement photographs need their own reviewed provenance and recorded derivation before assignment; this legacy-source renderer deliberately refuses unrecorded originals. PDF export requires DejaVu Sans fonts to preserve pagination. For lossless badges, use `soffice --headless --convert-to 'pdf:writer_pdf_Export:{"UseLosslessCompression":{"type":"boolean","value":"true"},"ReduceImageResolution":{"type":"boolean","value":"false"}}' --outdir outputs/booklets outputs/booklets/*_PRODUCTION.docx`.

Run `python3 tools/check_image_uniqueness.py --report outputs/reports/DUPLICATE_IMAGE_REPORT.csv` to audit all entry assignments in `data/entries.csv`. It exits nonzero for prohibited reuse, missing/altered organic watermarks, or missing/unreadable images. The [duplicate-image report](outputs/reports/DUPLICATE_IMAGE_REPORT.csv) lists every entry in prohibited groups, preserving repeated codes and leading zeros; permitted conventional/organic pairs are excluded.

Automated comparison uses decoded, EXIF-oriented pixels and compares organic images to their recorded **unwatermarked originals** so that the badge cannot hide unrelated reuse. Different filenames, metadata, lossless formats, crops, resizing or colour adjustments do not create a new photograph. Visual review must additionally reject re-encoded, resized, cropped or otherwise altered copies; the automated check does not prove that photographs are visually distinct. Source documents remain unchanged; non-produce entries currently have no images.

## Sources and reports

[PickList.xml](sources/plu/PickList.xml) is the authority for item codes, English product descriptions, visibility flags, and duplicate investigation. It uses UTF-16 encoding. Preserve code strings, including leading zeros, and do not modify source values to resolve booklet discrepancies.

The final text-only master DOCX files, original visual booklets without `_CORRECTED` suffixes, supporting produce PDFs, and referenced photo assets were not supplied. They are not included in `sources/`.

Current reports:

- [BOOKLET_AUDIT_REPORT.xlsx](outputs/reports/BOOKLET_AUDIT_REPORT.xlsx): findings, coverage, per-image review results and rejected images.
- [DUPLICATE_PLU_REPORT.csv](outputs/reports/DUPLICATE_PLU_REPORT.csv): duplicate codes in the fruit and vegetable books.
- [DUPLICATE_IMAGE_REPORT.csv](outputs/reports/DUPLICATE_IMAGE_REPORT.csv): entries sharing identical image content, independent of PLU-code duplication.
- [PICKLIST_SYNC.csv](outputs/reports/PICKLIST_SYNC.csv) and [PRODUCTION_READINESS.json](outputs/reports/PRODUCTION_READINESS.json): current WorkingList blockers and readiness; [PRODUCTION_BLOCKERS.csv](outputs/reports/PRODUCTION_BLOCKERS.csv) records legacy pre-approval alongside historical findings.
- [PICKLIST_CATALOG.csv](outputs/reports/PICKLIST_CATALOG.csv), [PICKLIST_SYNC.csv](outputs/reports/PICKLIST_SYNC.csv) and [PICKLIST_SYNC.json](outputs/reports/PICKLIST_SYNC.json): full XML catalogue and authoritative reconciliation, including records omitted by legacy books.
- [IMAGE_REQUESTS.csv](outputs/reports/IMAGE_REQUESTS.csv): new/unassigned records needing candidate image discovery; [INACTIVE_ASSIGNMENTS.csv](outputs/reports/INACTIVE_ASSIGNMENTS.csv): removed/hidden/replaced associations retained for review.
- [MASTER_IMAGE_LIBRARY.csv](outputs/reports/MASTER_IMAGE_LIBRARY.csv): entry-to-image assignments and reported sources.
- [IMAGE_MATCH_REPORT.csv](outputs/reports/IMAGE_MATCH_REPORT.csv): automated match confidence and image-quality notes.

Image paths in the CSV reports point to standalone copies of each booklet image under [data/images/](data/images/); [data/image_review.csv](data/image_review.csv) holds the full per-entry review table.

The approved subset of the produce image library includes current, identity-matched entries explicitly approved for their exact WorkingList identity or exact legacy identity. Legacy approval follows the owner's policy that every legacy entry is pre-approved, including entries with historical rejected or approximate verdicts. For those entries, the library records `APPROVED_LEGACY` and `OWNER_LEGACY_PREAPPROVED_POLICY`, while retaining the original verdict, rights/provenance fields, dimensions and source checksums as historical evidence. Legacy approval does not rewrite those underlying source records, establish new licence facts, or waive unrelated reconciliation and image-reuse gates. Each image is a 500 × 500 RGB JPEG (`.jpg`, quality 90, optimized and progressive), fitted without cropping or stretching on a solid white background. Small originals are padded without upscaling; a 500 × 500 library copy does not satisfy the source-resolution requirement. Transparent originals are composited onto white; organic images also carry the standard pink badge before JPEG encoding. Original files remain unchanged under `data/images/` or in their documented source documents. Production publication remains blocked until all applicable reconciliation and image requirements pass.

The image approval helper automatically refreshes the library after each approval. If a refresh fails, the helper reports that the approval was saved and the library needs attention. To refresh after other source or registry changes, run `python3 tools/build_image_library.py --refresh`; it checks the existing index and asset checksums before replacing managed files, and refuses to overwrite unmanaged files. For an isolated snapshot instead, run `python3 tools/build_image_library.py --output /path/to/empty/image-library`. Commit the updated library with the approval; `python3 tools/build_image_library.py --check` and the image-verification workflow flag stale snapshots. Future production DOCX and Excel builds use the same 500 × 500 rendering; the existing published booklets are not altered while release gates are blocked.

The single local library, `sources/image-library/`, also keeps a 500 × 500 white-background JPEG copy of **every used image**, including unapproved non-legacy review references and images retained in legacy booklets. `IMAGE_LIBRARY.csv` indexes approved current and exact-identity legacy entries; `WORKING_LIST_IMAGES.json` and `LEGACY_BOOKLET_IMAGES.json` retain use mappings and historical verdicts in the same directory. Legacy entries are always treated as pre-approved, and previously rejected or approximate legacy images are included; invalid, checksum-changed or identity-mismatched associations remain excluded. Run `python3 tools/used_image_library.py` to inventory those uses. The indexes retain source identities, paths, checksums and original provenance/review data, never cashier-facing labels.

Content-addressed JPEGs are reused after checksum and format validation, and unchanged files are not rewritten. Source bytes, renderer code, Pillow version and (when applied) organic badge artwork determine the cache key, so changed inputs cannot silently reuse stale derivatives. Production DOCX/Excel rendering and approved-library generation share this cache to avoid repeated JPEG encoding. Original assets and existing booklet appearance remain unchanged; legacy approval is distinct from approval of changed WorkingList identities and from image-reuse publication gates. Keep the library locally between runs or commit it with its indexes to make it available on fresh checkouts. `python3 tools/used_image_library.py --check` validates the cached JPEGs and usage associations; `python3 tools/build_image_library.py --check` additionally checks that the approved index is current.

## Keeping the repository organized

Automatic candidate acquisition checks `sources/image-library/` before any online search: exact-identity approved images first, then pre-approved legacy images, then reviewed local references. A matching local image stops online searching and is copied into the acquisition package with its existing approval status and provenance. Reviewed references remain unapproved; local reuse never clears publication or uniqueness gates. Changed identities do not inherit old approvals, and conflicting same-priority images require review rather than an arbitrary choice. Explicit owner-URL/reference fetches remain explicit requests, not automatic searches.

Online downloads also retain a JPEG display copy in the single local library; their acquisition provenance records the library path. Unreviewed downloads do not become approved associations merely by being cached. The goal is to grow coverage over time, not to assume the library already covers every possible product. New product identities and new image options still need owner review before becoming reusable approved associations.

### Replacement image retrieval and checks

Accepted image licence types are CC0 1.0; CC BY 2.0, 3.0 and 4.0; CC BY-SA 2.0, 3.0 and 4.0; and individually verified public-domain works. Photographs need not be MIT-licensed. An accepted licence type is not individual rights clearance: verify the source declaration, creator (or documented anonymous authorship), licence version, and any third-party rights before use. A Public Domain Mark is not a licence or proof of public-domain status; record the actual basis for the claim.

CC BY and CC BY-SA require the applicable creator credit, source and licence information, and identification of changes as required by that version. Share-alike applies to adaptations of the photograph, not automatically to independent booklet material merely collected alongside it. Keep photo licensing distinct from the repository's software licence. Record any crop, background removal or other modification and comply with the applicable adaptation terms. CC0 and verified public-domain works have no copyright attribution requirement, but this project still preserves provenance.

Run `python3 tools/retrieve_commons.py --review data/image_review.csv --leads sources/temp_upload/candidates.json --output /tmp/produce-review --user-agent "PLU-image-review/1.0 (YOUR_CONTACT_URL)"` from the repository root (requires Pillow). It searches Wikimedia Commons separately for all 31 rejected entries using explicit variety-specific queries, trying known source pages first. Duplicate PLUs and organic entries stay separate. It accepts the supported licence declarations as acquisition leads, requiring creator information and at least 500 pixels on **both** sides. Generic or uncertain matches must still be rejected during review. The legacy command without `--review` searches only three products, using the same accepted licence types.

The package output directory must be empty. It contains unchanged originals with per-image provenance JSON (creator, source-page and original-file URLs, declared licence, attribution, dimensions, checksum and raw Commons metadata), a combined `provenance.json`, labelled contact sheets, and an `acquisition-report.csv` covering every rejected entry. Up to two candidates are retained per entry (`--per-entry 1..5`). Missing metadata, unsupported licences and undersized files are not admitted. Unsafe oversized or unreadable images are skipped and recorded in the report; acquisition continues with later candidates. Duplicate image content within a package is skipped, including across repeated PLUs; acquisition tries later candidates and leaves an entry UNRESOLVED if no unique eligible candidate remains. This is not a comparison against every historical or production photograph. No-result entries are explicitly UNRESOLVED; network errors fail the run while preserving its partial review package. Network access to Commons and its upload host is required.

Every new package also includes `license-register.csv`: one row per candidate/entry association with filename, PLU, original and source-page URLs, creator, declared licence/version/link, conditional commercial-use and modification permissions, attribution, share-alike, permission notes, and separate rights-verification and visual-approval statuses. These start as `NOT_VERIFIED` and `NOT_APPROVED`; licence eligibility never changes production verdicts. The attribution column is a draft from captured metadata, not a substitute for checking source-specific credit requirements. Public-domain permissions remain `UNVERIFIED` until the claim is substantiated. Preserve raw provenance alongside the CSV.

[data/candidate_license_register.csv](data/candidate_license_register.csv) records the 51 associations from acquisition run [42553673620](https://github.com/smokydastona/produce-plu-code-book/actions/runs/42553673620), not 51 unique photographs or approved images. To generate a fresh register from an existing package, run `python3 tools/license_register.py /path/to/provenance.json --output /path/to/new-license-register.csv`. This initializes unverified statuses and refuses to overwrite an existing register, preserving manual review work.

Search matches and Commons licence declarations are leads, not proof of variety, photographic origin, organic certification, or rights ownership. Review the original source page and photograph before approval; icons, illustrations, synthetic images, third-party watermarks, and uncertain varieties remain unacceptable. The project's own standard pink ORGANIC identification label is the only permitted watermark. Nothing is automatically assigned to a booklet or marked approved. No production register is modified by acquisition.

The `verify-images.yml` workflow runs on pull requests and pushes to `main`. It checks added or modified images under `data/images/` and `sources/`, including images whose provenance JSON changes. Checked images are compared against all standalone images in those folders and each other. Assignment changes are also compared against the base commit: newly introduced prohibited sharing or missing/altered organic labels fail. Unchanged legacy duplicate groups are warned about, not approved; full compliance still requires the separate uniqueness and production-readiness audits to pass.

Each new photograph needs an adjacent `filename.ext.json` record following the downloader's format. Run `python3 tools/verify_images.py path/to/image.jpg` locally for candidate checks. Owner-provided files may use `OWNER_CONFIRMED_PERMISSION` with a source reference, owner attestation, and separate photo-origin and visual-approval evidence instead of a public licence; this records owner-confirmed use without inferring an open licence. Exact legacy identities follow the owner's blanket pre-approval policy; original rights, source and historical review records remain preserved as evidence. This does not grandfather changed WorkingList identities or waive unrelated source integrity and image-reuse requirements. Checks otherwise reject corrupt or multiframe images and invalid checksums; they do **not** independently verify licence claims. Cropped candidates must still meet the 500-pixel minimum and have dimensions updated in their records.

For isolated candidate downloads and a human-review checklist, see [sources/temp_upload/README.md](sources/temp_upload/README.md). Trigger `fetch-candidates.yml` manually with `scope=rejected` to acquire legacy rejected entries, or `scope=working-list-rejected` to acquire candidates only for rejected, identity-pinned entries in `IMAGE_VISUAL_REVIEW.csv`. Supply its `sequence` input to search one review entry at a time; the optional `search_query` input can refine that single entry's Commons terms. An `owner_image_url` can retrieve a user-provided Google Photos image for one sequence, with the original bytes and owner attestation included in the artifact; this does not assign or approve it for production. Visual review requires the individual produce item on a white or transparent background; reject cooked dishes and unrelated scenes. Artifacts include contact sheets, unchanged originals, provenance and unresolved/error results, and expire after seven days. The workflow never updates production registers.

For the full production backlog, select `scope=all` in that workflow and choose `per_entry=1..5`. It derives `ALL_IMAGE_REQUESTS.csv` from the current XML, including unassigned products and excluding only explicitly reviewed code-only entries. Six non-overlapping entry shards run with at most two concurrent jobs on GitHub-hosted runners, where Commons is reachable. Select a numbered `shard` to rerun only that shard. Each shard uploads `unreviewed-produce-images-N` (originals) and `candidate-review-metadata-N` (small provenance/register/report/contact-sheet package). Locally, first run `python3 tools/sync_picklist.py --catalog-only --output /tmp/picklist-sync`, then pass `--review /tmp/picklist-sync/ALL_IMAGE_REQUESTS.csv --all-entries --shard-count 6 --shard-index 0` to the retrieval command and repeat indices 0 through 5 in separate empty output directories, without the legacy `--leads` argument. XML-derived requests use the product description, not legacy index-based queries or leads. Search requires the product terms, not an exact phrase. Every query and result is recorded. Cross-shard image reuse must still be reviewed, and no search result is automatically a production image or rights approval.

After automatic acquisition, the workflow runs `tools/probe_image_sources.py` only when shard zero still has unresolved images. It checks alternative library addresses, requests discovery searches for entries #361, #368, #370 and #433, and retrieves the Fruits-360 original-size file tree. Its separate `source-discovery` artifact preserves responses and a per-request CSV, including network failures. HTTP success does not establish that a site honored the search query, returned photos, or grants reuse rights. Failed probes produce a workflow warning. These probes do not download or approve alternative-source images.

To opt into the local discovery-stage commit guard, copy `tools/hooks/pre-commit` to the repository's active Git hooks directory as `pre-commit` and make it executable. Check for an existing hook first and merge its behavior rather than overwriting it. The guard blocks staged changes under `outputs/` or `data/`; explicitly use `ALLOW_REGISTER_UPDATE=1 git commit ...` for authorized updates. Local hooks can be bypassed and do not enforce server-side protection. CODEOWNERS requires valid maintainer identities, and GitHub branch rules must separately require code-owner review and the desired number of approvals.

Put new supplied inputs in `sources/` and latest outputs in `outputs/`. Remove superseded review outputs while retaining source and review evidence and the last published booklets until production publication is permitted. Preserve duplicate records and keep generated documents out of the repository root.
