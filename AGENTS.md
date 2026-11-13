# Authoritative PickList and Reviewed Working List

- Never edit, normalize, repair, replace, or overwrite
  `sources/plu/PickList.xml`. Only @smokydastona may update it.
- PickList.xml remains the authoritative source of imported records.
  XML parse/structure failures must be reported, never automatically repaired.
- Generate `sources/plu/WorkingList.xml` from PickList.xml, then apply
  owner-approved product names, duplicate merges and association decisions.
- Generate cashier-facing binders and booklets from WorkingList.xml.
- Preserve original XML records and exact values in separate audit reports.
  Record every working-list override and its originating source identities.
- When PickList.xml changes, recreate WorkingList.xml and reapply decisions
  only where the original identities still match. Flag new, changed or
  ambiguous records for review; never silently reuse stale decisions.
- Preserve PLU strings, including leading zeros, and source visibility rules.
- Product decisions do not automatically approve images. New or changed
  product identities require fresh image review.
- Keep image provenance and review metadata outside cashier-facing entries.
- Block production publication until working-list reconciliation and image
  approvals pass. Keep the last published booklets intact when blocked.