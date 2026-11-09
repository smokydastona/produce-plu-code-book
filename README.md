# Cashier PLU Reference Booklets

Fruit, vegetable, and non-produce cashier references, their audit reports, and the supplied source documents.

## Where to find files

| Folder | Contents |
| --- | --- |
| [current/booklets/](current/booklets/) | Latest fruit, vegetable, and non-produce booklets in editable DOCX and printable PDF formats. |
| [current/review-booklets/](current/review-booklets/) | New AI-reference review editions in DOCX/PDF/XLSX, with image mapping, remaining blanks and actual validation results; not a production release. |
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

Every future approved build also includes one Excel (`.xlsx`) version per booklet, using the same filename stem as its DOCX/PDF. Excel versions are not yet published for the blocked current catalogue.

## Updating the complete till binder

`tools/build_till_binders.py` creates two **complete copies** of an existing till binder, replacing only its Produce section:

- `Complete Till Binder - Updated - Text Only.xlsx`
- `Complete Till Binder - Updated - Photos.xlsx`

Keep the original `Complete Till Binder - Nov 2025.xlsx` unchanged. The uploaded original is an external input, not fabricated from repository booklets. Run from the repository root with Pillow, python-docx (including lxml), openpyxl and pypdf installed. Print verification additionally requires **LibreOffice Calc**, not just Writer, and DejaVu Sans fonts.

```bash
python tools/build_till_binders.py \
  --binder "/path/to/Complete Till Binder - Nov 2025.xlsx" \
  --output "/path/to/empty/till-binder-review" \
  --verify-print --booklets
```

The output directory must be empty. Neither the original workbook nor the owner-maintained XML is modified. After a future owner XML upload, repeat the same command with a new empty output directory. Alternatively, the manually triggered **Build till-binder review copies** Actions workflow accepts the repository-relative path of an original workbook you have deliberately uploaded to the repository; it fails explicitly if that file is missing. Do not upload internal operational/contact information to a public repository merely to run Actions: local generation works with an external file.

Both editions use the same compact three-block layout and exact XML codes/descriptions, with normal category headings, organic entries following their confidently identified conventional counterparts, and duplicate PLUs highlighted red. Unknown classifications and ambiguous counterparts are retained and flagged in a separate report. Known non-produce records are excluded from Produce; unrelated operational sheets are not silently rewritten from the PLU master.

**No image-source/review labels, rights notes or audit metadata are printed beside cashier entries.** Entries contain only the PLU, exact product description and optional small image; organic images retain the requested upper-left pink seal. Audit details stay outside the binder. Source images are extracted directly from the supplied corrected visual DOCX files, matched by exact code/description plus the existing identity-linked assignment and checksum. Approximate photographic, rejected, changed-checksum, missing or ambiguous associations remain blank unless a new product-specific AI review reference is supplied as described below. At the owner's request, existing identity-linked **AI-only illustrations remain as visual references**, including uncertain pre-existing visual verdicts; their AI origin and review concerns appear only in `PHOTO_MAPPING.csv`, not on cashier entries. The five rejected wrong-product legacy AI images (including lettuce images incorrectly associated with squash) are never reused; newly reviewed product-specific crops can fill those slots without changing the old rejection verdicts. The other 145 legacy AI references remain. These are not certified photographs. Existing supplied references do not acquire photographic-origin, rights, resolution or reuse approval merely by appearing in a review copy.

The original XLSX is **not loaded and resaved** to produce the result. Only the Produce worksheet XML/relationships are replaced; new styles are appended without changing existing style definitions, new image/drawing parts are namespaced, and only Produce print names/content types are added. All original package parts remain present. Validation checks every unrelated original part byte-for-byte, all original styles, unrelated workbook-level settings, internal relationships, worksheet names/order, exact text cells, duplicate warnings, image bytes and image anchors. This preserves unrelated data, formulas, formatting, images, charts, comments, print settings and opaque objects instead of trusting an openpyxl round-trip to preserve unsupported features.

Each generation writes `PRODUCE_CHANGE_AND_VALIDATION_REPORT.txt`, `VALIDATION.json`, original-to-current comparison CSVs, all active duplicate-code associations, excluded-record details, `PHOTO_MAPPING.csv`, `PLACEMENT_REVIEW.csv`, per-cell/page layout, package-preservation hashes and the full XML reconciliation reports. Old abbreviated/contextual descriptions are not automatically treated as renamed products; uncertain matches remain explicit.

`--verify-print` opens/exports the **actual assembled complete workbooks** in Calc and retains **Produce-only PDF previews** in `print-previews/`. It verifies page count and landscape US Letter size, finds every code/description on its planned page, and checks actually drawn image counts. With `--booklets`, the complete binder PDFs are also retained locally, alongside three standalone review booklets in `booklets/` (fruit, vegetable and non-produce), each in DOCX, XLSX and, with `--verify-print`, PDF. Booklet PDF export additionally requires LibreOffice Writer. Booklets show only product names, PLUs and available images; duplicate codes remain red and image metadata stays in the external reports. The non-produce supplement remains code-only.

These checks do not replace visual inspection or a store-printer test. All these files are **review deliverables, not a production release**; outstanding XML/image approvals continue to block publication of the production booklets. The original November binder and previously published booklets remain intact. Generated complete binder copies and PDFs belong in an external directory or gitignored `current/review/`, so unrelated internal workbook information is not inadvertently committed. Only the standalone review booklets and their non-operational image reports may be copied to `current/review-booklets/` for repository sharing.

### Supplied AI contact-sheet references

The owner-supplied AI contact sheets and reviewed crop manifests live in `data/review-references/`. Review generation incorporates 121 new product-specific crops, removes their printed labels, and applies the standard upper-left pink seal to organic entries. The latest corrected sheet replaces five previously unsuitable panels (Sing Qua, both acorn squashes, Italian eggplant, and cooking papaya). The owner clarified that PLU 94391 is an organic orange, usually Buck Brand; its corresponding AI panel is retained as a review candidate, pending variety verification against the supplied Buck Brand specialty citrus infographic. The linked infographic could not be fetched in this environment because DNS resolution is unavailable. On small crops the seal stays at 30% of the shortest side instead of using the legacy 40-pixel minimum, which would obscure the product; legacy rendering is unchanged. The five formerly omitted duplicate records are linked to explicit XML source IDs; their existing duplicate counterparts are not overwritten. A matching conventional Cara Cara reference is reused for its organic entry with the pink badge, as permitted by the owner. The six overlapping citrus options use the larger second contact sheet.

All currently mapped Produce entries have an image in the review edition; this does not mean every image is verified. `AI_REFERENCE_REVIEW.csv` records exact identities, source checksums, crop boxes and remaining review concerns. `MISSING_IMAGES.csv` lists any blank references. The previous “all candidates covered” statement meant label coverage, not suitability or incorporation.

The generator verifies source hashes and crop bounds and refuses ambiguous identity reuse. After an XML identity changes or disappears, its old crop is not reassigned: the audit explicitly reports `NO_ACTIVE_EXACT_IDENTITY`. These small AI illustrations remain review references, not verified photographs, image-rights approvals or production-approved assets. No flags in `data/picklist_assignments.json` or existing visual verdicts are changed, and the production `sync_picklist.py` pipeline does not consume these review-only manifests.

## Updating PickList.xml in the future

**Only @smokydastona updates [sources/plu/PickList.xml](sources/plu/PickList.xml).** Upload a replacement at that exact path. The committed XML is assumed correct: scripts and agents never edit, repair or "correct" its product values. Neither the old booklets nor image spreadsheets override it.

The **Sync owner PickList** Actions workflow runs automatically when the XML changes (and after image-assignment changes), or can be run manually:

1. Read the complete XML, keeping code strings (including leading zeros), exact English descriptions, duplicate records and source order in the catalogue. Visible, non-deleted items are included; hidden/deleted items are excluded.
2. Reconcile image assignments using an identity derived from **code + exact description + department + duplicate occurrence**. Reordering unrelated items or changing XML encoding does not lose assignments. A new/changed code, description or department requires a new review; no approval is guessed from a similar name.
3. Search Commons automatically for entries with no assigned image, capturing eligible candidate originals, provenance, contact sheets and licence-review records in a `picklist-review-<commit>` artifact. Downloads are **not approvals**. No eligible result remains explicitly unresolved.
4. **Stop publication if any entry lacks an approved image or fails another gate.** Existing booklets under `current/booklets/` remain unchanged. Review `PICKLIST_SYNC.csv`, `IMAGE_REQUESTS.csv` and `PICKLIST_SYNC.json` in the artifact. Unknown products also need fruit/vegetable/non-produce classification, not a guessed category.
5. Once all gates pass, build all three booklets in DOCX, PDF and Excel (`.xlsx`) directly from that XML in an isolated staging directory, verify PDF code order/page size and Excel entries/source checksum, and provide `picklist-booklets-<commit>` for your final review. The workflow never writes the XML, overwrites published files, or silently publishes a failed build.

The existing 46-entry non-produce code-only supplement is preserved as an explicit exception; new entries are **not** silently made code-only. Every produce image needs visual/photographic and rights approval, a supported licence, provenance, matching checksum and at least 500 pixels on both sides. Every organic photograph gets the uploaded upper-left pink seal during rendering. In the new XML-driven pipeline, photo reuse requires an **explicit reviewed `reuse_from_source_id`** pointing to the matching conventional entry; organic codes are never inferred or rewritten. Any non-permitted repeated photograph blocks the build.

**Booklet order:** Organic entries do not have a separate organic section. Within each normal produce category, all conventional sizes/duplicate records for a product are grouped together, immediately followed by its organic entries. Description matching ignores the organic label, size words, common plurals and word order; it never changes the printed source values or guesses a match from a PLU. Reviewed `reuse_from_source_id` links also identify counterparts. An optional `placement_after_source_id` in the assignment registry records a reviewed conventional counterpart independently of photo reuse. It must reference an included conventional entry in the same booklet.

Unmatched or ambiguous organic entries stay at the end of their normal produce category, not in an organic section. `BOOKLET_ORDER.csv` records the exact presentation sequence, counterpart IDs and `PLACEMENT_REVIEW_REQUIRED` flags; `organic_placements_needing_review` summarizes those flags without adding a publication blocker. Legacy organic-only section labels are replaced for display using the product family; an unknown family falls back to the booklet's general category and remains flagged. This display categorization does not classify an unassigned XML record or approve any image. The XML catalogue remains in source order; both DOCX rendering and PDF verification use the derived booklet order.

Excel versions follow that same booklet order, with embedded photographs and the same pink badge on organic images. Each workbook has a filterable, freeze-pane `Booklet` sheet, landscape US Letter print settings, a source checksum, and a `Photo credits` sheet containing provenance, licensing and modification details. PLUs and descriptions are stored as literal text, preserving leading zeros, duplicate entries and names that begin with `=`. Non-produce code-only entries stay code-only. Excel generation runs behind the same image/reconciliation gates; `--catalog-only` never creates workbooks.

`data/picklist_assignments.json` is the review registry, **not an alternate PLU master**. Removed/hidden product assignments and assets are retained for audit but do not appear in newly generated books. Source descriptions/codes are always read afresh from XML. Truly identical duplicate records have no persistent ID in this XML format, so their occurrence number distinguishes them; adding/removing indistinguishable duplicates can require re-review. Candidate artwork and XML-referenced image filenames alone never establish an approved photo.

Local commands (Pillow, python-docx and openpyxl required):

```bash
# Catalogue/review reports only, never publication:
python3 tools/sync_picklist.py --catalog-only --output /tmp/new-picklist-review

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

The candidate needs its adjacent acquisition JSON and exact PLU/product association. Use `--replace` only when intentionally replacing an existing assignment; for permitted organic reuse also supply `--reuse-from CONVENTIONAL_SOURCE_ID`. This helper copies the unchanged original to `data/images/approved/`, records the checksum and review evidence, updates only the registry, and refuses stale-source reviews. Commit the new asset and registry; Actions reconciles and tries the gated build again. Don't set approval flags without doing the review.

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
