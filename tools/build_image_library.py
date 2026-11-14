"""Generate a local library of approved WorkingList produce images."""
import argparse
import csv
import hashlib
import json
import re
import tempfile
from pathlib import Path

from PIL import Image

from image_display import DISPLAY_SIZE
from sync_picklist import booklet_image, csv_output, reconcile
from verify_images import validate

ROOT = Path(__file__).resolve().parents[1]


def build_library(root, output):
    root, output = Path(root), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("library output must be empty; existing files are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="image-library-reconciliation-") as directory:
        rows, images, assignments, summary = reconcile(root, Path(directory))
    records = []
    for row in rows:
        if row["book"] not in {"Fruit", "Vegetable"} or row["blockers"]:
            continue
        assignment = assignments[row["source_id"]]
        legacy_original = assignment.get("legacy_organic_original")
        original_reference = (legacy_original["source_document"] + "#" + legacy_original["source_member"]
                              if legacy_original else assignment["image"])
        content = booklet_image(row, images)
        name = row["source_id"] + ".png"
        image_path = output / name
        provenance = dict(assignment["provenance"])
        metadata = dict(
            provenance, plu=row["plu"], product=row["name"],
            width=DISPLAY_SIZE[0], height=DISPLAY_SIZE[1],
            sha256=hashlib.sha256(content).hexdigest(),
            approval_status="CANDIDATE",
            photographic_origin=("OWNER_CONFIRMED_PHOTO"
                                 if provenance.get("rights_status") == "OWNER_CONFIRMED_PERMISSION"
                                 else "VERIFIED_PHOTO"),
            visual_approval_status=assignment["visual_approval_status"],
            rights_verification_status=assignment["rights_verification_status"],
            original_image_sha256=assignment["image_sha256"],
            original_image_path=original_reference,
            assigned_image_path=assignment["image"],
            legacy_organic_original=legacy_original,
            working_source_id=row["source_id"],
            working_source_ids=row["source_ids"],
            transformation="Aspect-ratio-preserving resize and centered white padding to 500x500 PNG"
                           + ("; standard pink organic badge added" if row["organic"] else ""),
        )
        image_path.write_bytes(content)
        metadata_content = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        image_path.with_suffix(".png.json").write_bytes(metadata_content)
        errors = validate(image_path)
        if errors:
            raise ValueError(f"{name}: {'; '.join(errors)}")
        with Image.open(image_path) as image:
            if image.size != DISPLAY_SIZE:
                raise ValueError(f"{name}: incorrect library image dimensions")
        records.append(dict(
            source_id=row["source_id"], source_identity_ids=";".join(row["source_ids"]),
            plu=row["plu"], product=row["name"], book=row["book"], image=name,
            image_sha256=metadata["sha256"], original_image=original_reference,
            assigned_image=assignment["image"],
            metadata_sha256=hashlib.sha256(metadata_content).hexdigest(),
            original_sha256=assignment["image_sha256"],
            visual_approval_status=assignment["visual_approval_status"],
            rights_verification_status=assignment["rights_verification_status"],
            photographic_origin=assignment["photographic_origin"],
            transformation=metadata["transformation"],
        ))
    csv_output(output / "IMAGE_LIBRARY.csv", records, [
        "source_id", "source_identity_ids", "plu", "product", "book", "image",
        "image_sha256", "metadata_sha256", "original_image", "assigned_image", "original_sha256",
        "visual_approval_status",
        "rights_verification_status", "photographic_origin", "transformation",
    ])
    if hashlib.sha256((root / "sources/plu/PickList.xml").read_bytes()).hexdigest() != summary["source_sha256"]:
        raise ValueError("PickList changed during library generation; discard output and retry")
    return dict(source_sha256=summary["source_sha256"], images=len(records),
                catalogue_status=summary["status"],
                records_needing_review=summary["records_needing_review"],
                blockers_by_source_id={row["source_id"]: row["blockers"] for row in rows
                                       if row["blockers"]})


def library_records(path):
    with (path / "IMAGE_LIBRARY.csv").open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    seen = set()
    for row in rows:
        name = row["image"]
        if not re.fullmatch(r"[0-9a-f]{64}\.png", name) or name != row["source_id"] + ".png" or name in seen:
            raise ValueError(f"invalid or repeated library image name: {name}")
        seen.add(name)
        for filename, key in ((name, "image_sha256"), (name + ".json", "metadata_sha256")):
            asset = path / filename
            if asset.is_symlink() or not asset.is_file() or hashlib.sha256(asset.read_bytes()).hexdigest() != row[key]:
                raise ValueError(f"library asset changed or missing: {asset}")
    return rows


def refresh_library(root):
    root = Path(root)
    library = root / "sources/image-library"
    if library.is_symlink():
        raise ValueError("library directory must not be a symlink")
    library.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="image-library-", dir=library.parent) as temp:
        staged = Path(temp)
        result = build_library(root, staged)
        new_rows = library_records(staged)
        index = library / "IMAGE_LIBRARY.csv"
        if index.is_symlink():
            raise ValueError("library index must not be a symlink")
        if index.exists():
            old_rows = library_records(library)
        elif library.exists() and any(library.iterdir()):
            raise ValueError("library has existing files but no index; refusing to overwrite")
        else:
            old_rows = []
        old_names = {row["image"] + suffix for row in old_rows for suffix in ("", ".json")}
        new_names = {row["image"] + suffix for row in new_rows for suffix in ("", ".json")}
        for name in new_names - old_names:
            if (library / name).exists() or (library / name).is_symlink():
                raise ValueError(f"unmanaged library file would be overwritten: {library / name}")
        library.mkdir(parents=True, exist_ok=True)
        for name in sorted(new_names):
            (staged / name).replace(library / name)
        for name in sorted(old_names - new_names):
            (library / name).unlink()
        (staged / "IMAGE_LIBRARY.csv").replace(index)
        result["source_ids"] = [row["source_id"] for row in new_rows]
        return result


def check_library(root):
    root = Path(root)
    library = root / "sources/image-library"
    if library.is_symlink() or (library / "IMAGE_LIBRARY.csv").is_symlink():
        raise ValueError("library and index must not be symlinks")
    current = library_records(library)
    with tempfile.TemporaryDirectory(prefix="image-library-check-") as directory:
        staged = Path(directory)
        result = build_library(root, staged)
        expected = library_records(staged)
        current_names = {"IMAGE_LIBRARY.csv"} | {
            row["image"] + suffix for row in current for suffix in ("", ".json")}
        expected_names = {"IMAGE_LIBRARY.csv"} | {
            row["image"] + suffix for row in expected for suffix in ("", ".json")}
        if (current_names != expected_names or
                {path.name for path in library.iterdir()} != current_names):
            raise ValueError("image library inventory is stale or contains unmanaged files")
        for name in sorted(current_names):
            if (library / name).read_bytes() != (staged / name).read_bytes():
                raise ValueError(f"image library is stale: {name}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output", type=Path, help="Empty library output directory")
    group.add_argument("--refresh", action="store_true", help="Refresh the managed repository library")
    group.add_argument("--check", action="store_true", help="Verify the repository library is current")
    args = parser.parse_args()
    try:
        if args.refresh:
            result = refresh_library(args.root)
        elif args.check:
            result = check_library(args.root)
        else:
            result = build_library(args.root, args.output)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"blockers_by_source_id", "source_ids"}}, indent=2))


if __name__ == "__main__":
    main()
