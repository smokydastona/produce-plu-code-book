"""Cache JPEG display copies without changing source images or review decisions."""
import argparse
import csv
import hashlib
import io
import json
import tempfile
from pathlib import Path

import PIL
from PIL import Image

import image_display
from image_display import DISPLAY_SIZE, display_image
import organic_watermarks

ROOT = Path(__file__).resolve().parents[1]


def digest(content):
    return hashlib.sha256(content).hexdigest()


def save_if_changed(path, content):
    if path.is_symlink():
        raise ValueError(f"library asset must not be a symlink: {path}")
    if path.exists() and path.read_bytes() == content:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(content)
            temporary.flush()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def jpeg_copy(root, content, organic=False):
    library = Path(root) / "sources/image-library"
    if library.is_symlink():
        raise ValueError("used image library must not be a symlink")
    library.mkdir(parents=True, exist_ok=True)
    rendering = dict(
        source_sha256=digest(content), organic=organic, pillow=PIL.__version__,
        renderer_sha256=digest(Path(image_display.__file__).read_bytes()),
    )
    if organic:
        rendering.update(
            watermark_renderer_sha256=digest(Path(organic_watermarks.__file__).read_bytes()),
            badge_sha256=digest((organic_watermarks.ROOT / organic_watermarks.BADGE_SOURCE).read_bytes()),
        )
    key = digest(json.dumps(rendering, sort_keys=True).encode())
    path = library / (key + ".jpg")
    metadata_path = library / (key + ".jpg.json")
    if path.is_symlink() or metadata_path.is_symlink():
        raise ValueError(f"library asset must not be a symlink: {path}")
    if path.exists() or metadata_path.exists():
        if not path.is_file() or not metadata_path.is_file():
            raise ValueError(f"incomplete JPEG library asset: {path}")
        metadata = json.loads(metadata_path.read_text())
        rendered = path.read_bytes()
        if metadata.get("rendering") != rendering or metadata.get("sha256") != digest(rendered):
            raise ValueError(f"JPEG library checksum mismatch: {path}")
        reused = True
    else:
        rendered = display_image(content, organic=organic)
        reused = False
    with Image.open(io.BytesIO(rendered)) as image:
        image.load()
        if image.format != "JPEG" or image.mode != "RGB" or image.size != DISPLAY_SIZE:
            raise ValueError(f"invalid JPEG library display copy: {path}")
    if not reused:
        save_if_changed(path, rendered)
        save_if_changed(metadata_path, (json.dumps(dict(
            rendering=rendering, sha256=digest(rendered),
            approval_status="NOT_GRANTED_BY_LIBRARY",
        ), indent=2) + "\n").encode())
    return path, rendered, reused


def record_images(root, name, images, records):
    associations = []
    reused = 0
    for record in records:
        identity = record["source_id"]
        if identity not in images:
            continue
        path, content, cached = jpeg_copy(root, images[identity])
        reused += cached
        associations.append(dict(
            record, library_image=str(path.relative_to(root)),
            library_sha256=digest(content),
            library_source_sha256=digest(images[identity]),
            library_approval_status=record.get("library_approval_status", "NOT_APPROVED"),
        ))
    library = Path(root) / "sources/image-library"
    library.mkdir(parents=True, exist_ok=True)
    save_if_changed(library / name, (json.dumps(
        associations, ensure_ascii=False, indent=2) + "\n").encode())
    return dict(images=len(associations), reused=reused)


def check_used_library(root, directory=None):
    library = Path(directory) if directory is not None else Path(root) / "sources/image-library"
    if library.is_symlink():
        raise ValueError("used image library must not be a symlink")
    paths = set()
    if not library.exists():
        return paths
    approved_names = set()
    if (library / "IMAGE_LIBRARY.csv").exists():
        from build_image_library import library_records

        approved_names = {row["image"] + suffix for row in library_records(library)
                          for suffix in ("", ".json")}
    for path in library.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"invalid used image library asset: {path}")
        if path.name in approved_names or path.suffix != ".jpg":
            continue
        metadata_path = path.with_suffix(".jpg.json")
        if metadata_path.is_symlink():
            raise ValueError(f"library asset must not be a symlink: {metadata_path}")
        metadata = json.loads(metadata_path.read_text())
        key = digest(json.dumps(metadata["rendering"], sort_keys=True).encode())
        content = path.read_bytes()
        if path.stem != key or metadata["sha256"] != digest(content):
            raise ValueError(f"JPEG library checksum mismatch: {path}")
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            if image.format != "JPEG" or image.mode != "RGB" or image.size != DISPLAY_SIZE:
                raise ValueError(f"invalid JPEG library display copy: {path}")
        paths.add(path.resolve())
    for path in library.glob("*.jpg.json"):
        if not path.with_suffix("").is_file():
            raise ValueError(f"orphan JPEG library metadata: {path}")
    for name in ("WORKING_LIST_IMAGES.json", "LEGACY_BOOKLET_IMAGES.json"):
        index = library / name
        if not index.exists():
            continue
        for row in json.loads(index.read_text()):
            path = Path(root) / row["library_image"]
            if path.resolve() not in paths or digest(path.read_bytes()) != row["library_sha256"]:
                raise ValueError(f"used image association checksum mismatch: {path}")
            metadata = json.loads(path.with_suffix(".jpg.json").read_text())
            if metadata["rendering"]["source_sha256"] != row["library_source_sha256"]:
                raise ValueError(f"used image source association mismatch: {path}")
    return paths


def managed_cache_names(root):
    library = Path(root) / "sources/image-library"
    paths = check_used_library(root)
    names = {path.name + suffix for path in paths for suffix in ("", ".json")}
    names.update(name for name in ("WORKING_LIST_IMAGES.json", "LEGACY_BOOKLET_IMAGES.json")
                 if (library / name).exists())
    return names


def local_inventory(root):
    root = Path(root)
    library = root / "sources/image-library"
    if not library.exists():
        return []
    check_used_library(root)
    options = []
    index = library / "IMAGE_LIBRARY.csv"
    if index.exists():
        from build_image_library import check_library, library_records

        if (root / "data/picklist_assignments.json").exists():
            check_library(root)

        for row in library_records(library):
            tier = "LEGACY" if row.get("image_approval_status") == "APPROVED_LEGACY" else "APPROVED"
            options.append(dict(row, tier=tier, path=library / row["image"],
                                provenance=json.loads((library / (row["image"] + ".json")).read_text())))
    working_index = library / "WORKING_LIST_IMAGES.json"
    if working_index.exists():
        assignments_path = root / "data/picklist_assignments.json"
        assignments = None
        if assignments_path.exists():
            assignments = {
                row["source_id"]: row
                for row in json.loads(assignments_path.read_text())["assignments"]
            }
        current = None
        if (root / "sources/plu/WorkingList.xml").exists():
            from working_list import read_working_list

            rows, _ = read_working_list(root)
            current = {row["source_id"]: row for row in rows}
        for row in json.loads(working_index.read_text()):
            identity = row["source_id"]
            if current is not None:
                item = current.get(identity)
                if item is None or (item["plu"], item["name"]) != (row["plu"], row["product"]):
                    raise ValueError(f"stale local working image identity: {identity}")
            if assignments is not None:
                assignment = assignments.get(identity)
                if assignment != row.get("assignment"):
                    raise ValueError(f"stale local working image assignment: {identity}")
                if assignment and assignment.get("image"):
                    from sync_picklist import original_image

                    if digest(original_image(root, assignment)) != assignment.get("image_sha256"):
                        raise ValueError(f"changed local working image: {identity}")
            status = row.get("library_approval_status")
            tier = {"APPROVED": "APPROVED", "APPROVED_LEGACY": "LEGACY"}.get(status, "REVIEWED")
            if row.get("image_status") in {"REJECTED", "WORKING_IDENTITY_REVIEW_REQUIRED"}:
                continue
            options.append(dict(row, tier=tier, path=root / row["library_image"], provenance=row))
    legacy_index = library / "LEGACY_BOOKLET_IMAGES.json"
    if legacy_index.exists():
        for row in json.loads(legacy_index.read_text()):
            options.append(dict(row, tier="LEGACY", path=root / row["library_image"], provenance=row))
    rank = {"APPROVED": 0, "LEGACY": 1, "REVIEWED": 2}
    options.sort(key=lambda row: (rank[row["tier"]], str(row["path"])))
    return options


def local_options(root, entry, inventory=None):
    root = Path(root)
    library = root / "sources/image-library"
    identity = entry.get("source_id", "")
    options = [
        row for row in (local_inventory(root) if inventory is None else inventory)
        if (row.get("plu"), row.get("product", row.get("name"))) == (entry["plu"], entry["name"])
        and (not identity or row.get("source_id") == identity)
    ]
    unique = {}
    for row in options:
        unique.setdefault((row.get("source_id"), row["tier"]), row)
    options = list(unique.values())
    if options:
        best = options[0]
        peers = [row for row in options if row["tier"] == best["tier"]]
        if len({digest(row["path"].read_bytes()) for row in peers}) > 1:
            raise ValueError(f"ambiguous local images for {entry['plu']} / {entry['name']}; review required")
        path = best["path"]
        if path.resolve().parent != library.resolve() or not path.is_file():
            raise ValueError(f"invalid local image option: {path}")
        return [best]
    return []


def absorb_used_library(root):
    root = Path(root)
    previous = root / "sources/used-image-library"
    if not previous.exists():
        return
    paths = check_used_library(root, directory=previous)
    managed = {path.name + suffix for path in paths for suffix in ("", ".json")}
    managed.update(name for name in ("WORKING_LIST_IMAGES.json", "LEGACY_BOOKLET_IMAGES.json")
                   if (previous / name).exists())
    if {path.name for path in previous.iterdir()} != managed:
        raise ValueError("previous image library contains unmanaged files; merge refused")
    library = root / "sources/image-library"
    if library.is_symlink():
        raise ValueError("image library must not be a symlink")
    library.mkdir(parents=True, exist_ok=True)
    assets = {}
    for path in previous.iterdir():
        content = path.read_bytes()
        if path.name in {"WORKING_LIST_IMAGES.json", "LEGACY_BOOKLET_IMAGES.json"}:
            records = json.loads(content)
            for row in records:
                row["library_image"] = str(
                    (library / Path(row["library_image"]).name).relative_to(root))
            content = (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode()
        destination = library / path.name
        if destination.is_symlink() or (destination.exists() and destination.read_bytes() != content):
            raise ValueError(f"image library merge collision: {destination}")
        assets[path] = content
    for path, content in assets.items():
        save_if_changed(library / path.name, content)
    check_used_library(root)
    for path in assets:
        path.unlink()
    previous.rmdir()


def refresh_used_library(root):
    from build_till_binders import map_images, produce_catalog, visual_records
    from picklist_catalog import read_assignments
    from sync_picklist import safe_asset
    from working_list import read_working_list, rebuild_working_list

    root = Path(root)
    absorb_used_library(root)
    with tempfile.TemporaryDirectory(prefix="used-image-reconciliation-") as temporary:
        rebuild_working_list(root, Path(temporary))
    items, _ = read_working_list(root)
    assignments = read_assignments(root / "data/picklist_assignments.json")
    rows, _ = produce_catalog(items, assignments)
    images, report = map_images(root, rows, assignments, visual_records(root), update_library=False)
    result = record_images(root, "WORKING_LIST_IMAGES.json", images, [
        dict(record, assignment=assignments.get(record["source_id"], {}),
             library_approval_status=record["image_approval_status"])
        for record in report
    ])
    with (root / "data/entries.csv").open(newline="", encoding="utf-8-sig") as file:
        legacy = list(csv.DictReader(file))
    with (root / "data/image_review.csv").open(newline="", encoding="utf-8-sig") as file:
        reviews = {row["idx"]: row for row in csv.DictReader(file)}
    images, records = {}, []
    for row in legacy:
        identity = "legacy:" + row["idx"]
        images[identity] = safe_asset(root, "data/" + row["image"]).read_bytes()
        records.append(dict(
            row, source_id=identity, legacy_review=reviews.get(row["idx"], {}),
            image_status="LEGACY_PREAPPROVED_IMAGE",
            image_approval_status="APPROVED_LEGACY",
            approval_basis="OWNER_LEGACY_PREAPPROVED_POLICY",
            library_approval_status="APPROVED_LEGACY",
        ))
    result["legacy"] = record_images(root, "LEGACY_BOOKLET_IMAGES.json", images, records)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Check cached JPEGs and association checksums")
    args = parser.parse_args()
    try:
        result = (dict(jpegs=len(check_used_library(args.root))) if args.check
                  else refresh_used_library(args.root))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
