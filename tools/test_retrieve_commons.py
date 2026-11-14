import csv
import tempfile
import unittest
from pathlib import Path

from retrieve_commons import review_rejection_entries


class WorkingListCandidateRequests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.review_path = self.root / "IMAGE_VISUAL_REVIEW.csv"
        self.report = dict(
            source="sources/plu/PickList.xml",
            source_sha256="current-source-hash",
            reviewed_working_list_entries=2,
            decision_counts={"REJECTED": 1, "VISUALLY_SUITABLE": 1},
        )
        self.items = [
            dict(source_id="working-napa", source_ids=["source-napa"], plu="4552",
                 name="Napa Cabbage", included=True),
            dict(source_id="working-cilantro", source_ids=["source-cilantro"], plu="4889",
                 name="Cilantro", included=True),
        ]
        rows = [
            dict(sequence="4", working_list_id="working-napa", source_identity_ids="source-napa",
                 plu="4552", working_product="Napa Cabbage", visual_decision="REJECTED"),
            dict(sequence="15", working_list_id="working-cilantro", source_identity_ids="source-cilantro",
                 plu="4889", working_product="Cilantro", visual_decision="VISUALLY_SUITABLE"),
        ]
        with self.review_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_only_current_rejected_working_list_identities_become_search_requests(self):
        entries = review_rejection_entries(self.review_path, self.report, "current-source-hash", self.items)
        self.assertEqual(entries, [
            dict(idx="4", plu="4552", name="Napa Cabbage", source_id="working-napa"),
        ])

    def test_stale_source_or_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "different PickList"):
            review_rejection_entries(self.review_path, self.report, "changed-source-hash", self.items)

        changed_items = [dict(self.items[0], name="Different Product"), self.items[1]]
        with self.assertRaisesRegex(ValueError, "identity changed"):
            review_rejection_entries(self.review_path, self.report, "current-source-hash", changed_items)


if __name__ == "__main__":
    unittest.main()
