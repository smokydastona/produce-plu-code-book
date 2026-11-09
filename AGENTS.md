# Authoritative PickList

- Never edit, normalize, repair, replace, or overwrite `sources/plu/PickList.xml`.
  Only the repository owner, @smokydastona, may update it.
- Assume the committed XML's product values are correct. Preserve its code strings,
  English descriptions, visibility and duplicate records exactly in derived files.
  XML parse/structure failures must be reported, never automatically repaired.
- Generate catalogues from XML, not from existing booklets or image inventories.
- New or changed product identities require fresh image review. Never copy an
  approval to another description/code or mark downloaded candidates approved.
- Block booklet publication until the XML reconciliation and image approvals pass.
  Keep the last published booklets intact when reconciliation is blocked.
