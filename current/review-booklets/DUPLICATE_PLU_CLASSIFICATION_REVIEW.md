# Duplicate PLU decisions and WorkingList implementation

The CSV beside this report now records **applied WorkingList decisions**, not
annotation-only recommendations. Each decision is pinned to the exact original
source identity IDs in `data/working_list_decisions.json`. The authoritative
`sources/plu/PickList.xml` is unchanged. Every source record, including hidden,
deleted and conflicting records, remains in the external audit
`reconciliation/PICKLIST_SOURCE_RECORDS.xml`; the accompanying CSV maps each
source identity to its resulting WorkingList entry or exclusion.

## Current reconciliation

- PickList SHA-256:
  `462db3121094008cd1dd5ea2c5836ca4b24de077edb8982c0f43149edbaf2cbb`
- 724 original source records; 672 WorkingList records.
- 648 visible, non-deleted source records become 596 active WorkingList
  records, including 550 Produce and 46 Non-produce entries.
- 48 exact decision groups were applied; 7 non-selected source associations
  were removed from cashier presentation but retained in the source audit:
  6 owner-confirmed conflicting associations and the unconfirmed Clementines
  Box equivalence/packaging record for PLU 4458.
- PLU 94093 remains unstandardized pending supplier confirmation. PLU 4727
  displays **Yellow Potatoes**; the Yukon Gold alias was not added because
  inventory confirmation is absent.
- 48 changed WorkingList identities have no inherited image approval. Their
  candidates have completed a visual product-match review; the exact decisions
  and source identities are in `IMAGE_VISUAL_REVIEW.csv` and its JSON summary.
  These visual-only decisions do not approve rights, photographic origin,
  resolution or production use. All 48 remain blank in cashier-facing files.
  The regenerated review booklets embed 502 unchanged-identity references and
  are not a production release.

## Owner-reviewed cases

| PLU | Applied WorkingList presentation | Source association handling |
|---|---|---|
| 3038 | Orange Granadilla | Owner-confirmed same intended product as Passion Fruit; merged. |
| 4055 | Murcott Tangerines | Owner-confirmed same product; merged. |
| 4059 | Red Prince Apples | Selected the apple identity; Kiwi Small remains in the source audit as conflicting. |
| 4253 | Strawberries by the Flat | Selected the strawberry identity; Blueberries Quart remains in the audit as conflicting. |
| 4425 | Shinko (Shingo) Asian Pear | Selected the Shingo pear identity; Taylor Gold remains in the audit as conflicting. |
| 4458 | Tangerine Seedless | Selected as intended; Clementines Box equivalence and packaging were not confirmed or asserted. |
| 4893 | Dill | Owner-confirmed equivalent descriptions; merged. |
| 60271 | Early Nugget (Warba) Potatoes | Owner-confirmed same variety; merged. |
| 94040 | Organic Black Plums | Selected the plum identity; cantaloupe association remains in the audit as conflicting. |
| 94342 | Organic Watermelon | Owner-confirmed same product; merged. |
| 94769 | Organic Kabocha Squash | Selected the Kabocha identity; Stripetti remains in the audit as conflicting. |
| 94823 | Organic White Potatoes | Selected the white-potato identity; Nugget remains in the audit as conflicting. |

The remaining approved Merge/Standardize recommendations are also applied,
except for 94093's supplier-confirmation condition. Source records, exact
original values, and identity links are available in the reconciliation audit.

## Publication status

`current/review-booklets/` contains regenerated cashier-facing review files:
entries show only PLU, WorkingList product name and optional image. The
fruit, vegetable and non-produce layouts were verified as landscape US Letter;
image associations, exact text, PLU strings and leading zeros were checked.
Organic images retain the consistent pink upper-left badge. Provenance,
conflicts and review issues stay in external reports.

Publication remains **BLOCKED**. Visual review of the 48 changed identities is
complete, but visual suitability alone does not clear image rights,
photographic-origin, resolution, provenance or production gates; rejected
candidates still need replacements. Existing classification and reuse gates
remain, and PLU 94093 still needs supplier confirmation. The last production
booklets have not been overwritten.

The owner reuploaded the exact original workbook, now committed at
`sources/binders/Complete_Till_Binder_-_Nov_2025.xlsx`
(verified SHA-256
`6b0aeaa153233c5f4917811a3f7a5b2212f7a946a0abede372a31db556ab0f63`).
Both complete binder review editions were regenerated from WorkingList using
that unchanged original, never reconstructed from prior outputs. Each complete
PDF has 38 pages, including 10 Produce pages with 550 entries. The photo edition
embeds 502 unchanged-identity references; the 48 changed identities remain blank
despite their completed visual-only review.
All 14 worksheets and unrelated workbook objects, package parts, styles and
settings are preserved. See the complete-binder validation and preservation
reports in `current/review/till-binder-supplier-photos-final/`.
