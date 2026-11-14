"""Resolve the owner's blanket pre-approval policy for exact legacy image identities."""
import csv
from pathlib import Path


def legacy_entries(root):
    root = Path(root)
    entries_path = root / "data/entries.csv"
    reviews_path = root / "data/image_review.csv"
    if not entries_path.is_file() or not reviews_path.is_file():
        return {}
    with entries_path.open(newline="", encoding="utf-8-sig") as file:
        entries = list(csv.DictReader(file))
    with reviews_path.open(newline="", encoding="utf-8-sig") as file:
        reviews = list(csv.DictReader(file))
    by_id = {row["idx"]: row for row in reviews}
    if len(by_id) != len(reviews) or set(by_id) != {row["idx"] for row in entries}:
        raise ValueError("legacy image review and entry IDs must match exactly")
    result = {}
    for row in entries:
        review = by_id[row["idx"]]
        if any(row[key] != review[key] for key in ("book", "plu", "name", "image")):
            raise ValueError(f"legacy image review assignment mismatch for entry {row['idx']}")
        result[row["idx"]] = dict(row, historical_review=review)
    return result


def legacy_approval(root, item, assignment, entries=None):
    if item.get("identity_changed") or not assignment or not assignment.get("legacy_entry_idx"):
        return None
    entries = legacy_entries(root) if entries is None else entries
    entry = entries.get(str(assignment["legacy_entry_idx"]))
    if not entry or (entry["plu"], entry["name"]) != (item["plu"], item["name"]):
        return None
    if (assignment.get("reviewed_plu"), assignment.get("reviewed_product")) != (
            item["plu"], item["name"]):
        return None
    legacy_path = (Path(root) / "data" / entry["image"]).resolve()
    assignment_path = (Path(root) / assignment.get("image", "")).resolve()
    if legacy_path != assignment_path or not legacy_path.is_file():
        return None
    return entry
