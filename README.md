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

**Current means latest, not certified for production use.** The `_PRODUCTION` filenames were assigned during an earlier build and do not establish that all requested quality checks passed.

- The fruit and vegetable books contain 597 entries. Their images have not been independently validated for exact product or variety, and AI images and sub-500-pixel images remain.
- Some `VERIFIED PHOTO` labels were assigned using product-name similarity to PickList descriptions, not visual inspection. Do not treat those labels or the image-match confidence values as photographic verification.
- The non-produce supplement contains 46 visible PickList records representing 45 distinct codes omitted from the produce books. It preserves both `77974` entries (Cheese Bun and Pizza Bun). It is a code-and-label reference, not a photo-verified guide; referenced image files were not supplied.
- The collection does not include every PickList record, including hidden items. Current duplicate reports cover the produce booklet entries, not a complete investigation of all PickList records.
- Image licenses and provenance have not been independently established. Review them before redistributing the booklets.

## Sources and reports

[PickList.xml](sources/plu/PickList.xml) is the authority for item codes, English product descriptions, visibility flags, and duplicate investigation. It uses UTF-16 encoding. Preserve code strings, including leading zeros, and do not modify source values to resolve booklet discrepancies.

The final text-only master DOCX files, original visual booklets without `_CORRECTED` suffixes, supporting produce PDFs, and referenced photo assets were not supplied. They are not included in `sources/`.

Current reports:

- [BOOKLET_AUDIT_REPORT.xlsx](current/reports/BOOKLET_AUDIT_REPORT.xlsx): automated findings and coverage counts.
- [DUPLICATE_PLU_REPORT.csv](current/reports/DUPLICATE_PLU_REPORT.csv): duplicate codes in the fruit and vegetable books.
- [MASTER_IMAGE_LIBRARY.csv](current/reports/MASTER_IMAGE_LIBRARY.csv): entry-to-image assignments and reported sources.
- [IMAGE_MATCH_REPORT.csv](current/reports/IMAGE_MATCH_REPORT.csv): automated match confidence and image-quality notes.

Image paths in the CSV reports identify media embedded inside a DOCX package (for example, `Fruit/word/media/image1.jpg`); they are not standalone image files in this repository.

## Keeping the repository organized

Put new supplied inputs in `sources/`, latest outputs in `current/`, and superseded outputs in a clearly named version folder under `archive/`. Retain source files unchanged, preserve duplicate records, and regenerate the PDF and related reports whenever a booklet changes. Keep generated documents out of the repository root.
