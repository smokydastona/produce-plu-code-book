import csv
import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from picklist_catalog import read_picklist
from working_list import read_working_list, rebuild_working_list


class WorkingListChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "sources/plu").mkdir(parents=True)
        (self.root / "data").mkdir()
        (self.root / "data/picklist_assignments.json").write_text(
            json.dumps(dict(schema_version=1, assignments=[])))
        self.source = self.root / "sources/plu/PickList.xml"
        self.audit = self.root / "audit"
        self.write_source([
            ("00042", "Apple Red Prince", True),
            ("00042", "Kiwi Small", True),
            ("00043", "Pear", True),
        ])
        self.items, self.digest = read_picklist(self.source)
        self.write_registry([])

    def write_source(self, values):
        root = ET.Element("PickList")
        items = ET.SubElement(root, "Items")
        for plu, name, visible in values:
            item = ET.SubElement(items, "Item", UPC=plu, VendorCode="literal")
            ET.SubElement(item, "Department").text = "001"
            ET.SubElement(item, "IsVisible").text = str(visible)
            ET.SubElement(item, "DeleteThisItem").text = "False"
            language = ET.SubElement(ET.SubElement(item, "Languages"), "Language", LCID="0409")
            ET.SubElement(language, "Description").text = name
            ET.SubElement(item, "SourceValue").text = "Preserve exact source value"
        self.source.write_bytes(ET.tostring(root, encoding="utf-16"))

    def write_registry(self, decisions):
        baseline = [dict(source_id=item["source_id"], plu=item["plu"], name=item["name"],
                         department=item["department"], occurrence=item["occurrence"],
                         visible=item["visible"], deleted=item["deleted"]) for item in self.items]
        (self.root / "data/working_list_decisions.json").write_text(json.dumps(dict(
            schema_version=1, baseline_source_sha256=self.digest,
            baseline=baseline, decisions=decisions)))

    def merge_decision(self, selected=None):
        ids = [item["source_id"] for item in self.items[:2]]
        return dict(
            plu="00042", canonical_name="Red Prince Apples", mode="MERGE" if selected is None else "SELECT",
            source_ids=ids, selected_source_ids=ids if selected is None else [ids[selected]],
            condition="Owner-confirmed product decision")

    def test_merge_preserves_all_original_records_and_links_working_identity(self):
        source_before = self.source.read_bytes()
        self.write_registry([self.merge_decision()])
        rows, originals, summary = rebuild_working_list(self.root, self.audit)
        working, digest = read_working_list(self.root)
        selected = next(row for row in working if row["plu"] == "00042")
        self.assertEqual(selected["name"], "Red Prince Apples")
        self.assertEqual(selected["source_ids"], [item["source_id"] for item in originals[:2]])
        self.assertTrue(selected["identity_changed"])
        self.assertNotIn(selected["source_id"], selected["source_ids"])
        self.assertEqual(digest, self.digest)
        self.assertEqual(summary["source_records"], 3)
        self.assertEqual(summary["working_records"], 2)
        self.assertEqual(self.source.read_bytes(), source_before)
        audit = ET.parse(self.audit / "PICKLIST_SOURCE_RECORDS.xml").getroot()
        source_records = audit.findall("./Records/SourceRecord")
        self.assertEqual(len(source_records), 3)
        names = [row.findtext("./Item/Languages/Language[@LCID='0409']/Description")
                 for row in source_records]
        self.assertEqual(names, ["Apple Red Prince", "Kiwi Small", "Pear"])
        self.assertTrue(all(row.find("./Item/SourceValue").text == "Preserve exact source value"
                            for row in source_records))
        with (self.audit / "WORKING_LIST_RECONCILIATION.csv").open(
                encoding="utf-8-sig", newline="") as file:
            report = list(csv.DictReader(file))
        self.assertEqual({row["disposition"] for row in report[:2]}, {"MERGED_INTO_WORKING_ENTRY"})

    def test_conflicting_association_is_excluded_but_retained_in_full_audit(self):
        self.write_registry([self.merge_decision(selected=0)])
        rows, _, summary = rebuild_working_list(self.root, self.audit)
        code_rows = [row for row in rows if row["plu"] == "00042"]
        self.assertEqual(len(code_rows), 1)
        self.assertEqual(code_rows[0]["name"], "Red Prince Apples")
        self.assertEqual(summary["excluded_conflicting_source_records"], 1)
        with (self.audit / "WORKING_LIST_RECONCILIATION.csv").open(
                encoding="utf-8-sig", newline="") as file:
            report = list(csv.DictReader(file))
        conflict = next(row for row in report if row["original_name"] == "Kiwi Small")
        self.assertEqual(conflict["disposition"], "EXCLUDED_CONFLICTING_ASSOCIATION")
        self.assertFalse(conflict["working_id"])

    def test_unconfirmed_equivalence_is_audited_separately_from_conflicts(self):
        decision = self.merge_decision(selected=1)
        decision["excluded_source_disposition"] = "EXCLUDED_EQUIVALENCE_NOT_CONFIRMED"
        self.write_registry([decision])
        _, _, summary = rebuild_working_list(self.root, self.audit)
        self.assertEqual(summary["excluded_conflicting_source_records"], 0)
        self.assertEqual(summary["excluded_unconfirmed_equivalence_records"], 1)
        with (self.audit / "WORKING_LIST_RECONCILIATION.csv").open(
                encoding="utf-8-sig", newline="") as file:
            report = list(csv.DictReader(file))
        excluded = next(row for row in report if row["original_name"] == "Apple Red Prince")
        self.assertEqual(excluded["disposition"], "EXCLUDED_EQUIVALENCE_NOT_CONFIRMED")
        self.assertFalse(excluded["working_id"])

    def test_changed_source_identity_never_reuses_decision_and_is_flagged(self):
        self.write_registry([self.merge_decision()])
        self.write_source([
            ("00042", "Apple Red Prince", True),
            ("00042", "Kiwi Mini", True),
            ("00043", "Pear", True),
        ])
        rows, _, summary = rebuild_working_list(self.root, self.audit)
        code_rows = [row for row in rows if row["plu"] == "00042"]
        self.assertEqual([row["name"] for row in code_rows], ["Apple Red Prince", "Kiwi Mini"])
        decision = next(row for row in summary["decisions"] if row["decision_id"] == "00042")
        self.assertEqual(decision["status"], "DECISION_SOURCE_MISSING_OR_CHANGED")
        with (self.audit / "WORKING_LIST_RECONCILIATION.csv").open(
                encoding="utf-8-sig", newline="") as file:
            report = list(csv.DictReader(file))
        changed = next(row for row in report if row["original_name"] == "Kiwi Mini")
        self.assertEqual(changed["review_status"], "CHANGED_SOURCE_IDENTITY_REVIEW")

    def test_new_same_code_identity_is_not_silently_added_to_decision(self):
        self.write_registry([self.merge_decision()])
        self.write_source([
            ("00042", "Apple Red Prince", True),
            ("00042", "Kiwi Small", True),
            ("00042", "New Apple", True),
            ("00043", "Pear", True),
        ])
        rows, _, summary = rebuild_working_list(self.root, self.audit)
        code_rows = [row for row in rows if row["plu"] == "00042"]
        self.assertEqual(len(code_rows), 2)
        decision = next(row for row in summary["decisions"] if row["decision_id"] == "00042")
        self.assertEqual(decision["status"], "APPLIED_WITH_ADDITIONAL_SOURCE_REVIEW")
        new_row = next(row for row in rows if row["name"] == "New Apple")
        self.assertEqual(new_row["working_list_status"], "NEW_OR_AMBIGUOUS_PLU_IDENTITY_REVIEW")

    def test_stale_working_list_is_rejected_after_source_change(self):
        rebuild_working_list(self.root, self.audit)
        self.write_source([("00042", "Changed", True)])
        with self.assertRaisesRegex(ValueError, "WorkingList.xml is stale"):
            read_working_list(self.root)


if __name__ == "__main__":
    unittest.main()
