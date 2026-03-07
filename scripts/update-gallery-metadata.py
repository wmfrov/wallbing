#!/usr/bin/env python3
"""
Update gallery metadata.json: add optional new image, prune to target size (FIFO by date),
output image paths newest-first for building index.html.

Usage:
  python update-gallery-metadata.py SITE_ROOT [IMAGE_PATH DATE BYTES [TITLE]]
  e.g. python update-gallery-metadata.py . images/Photo.png 2025-03-06 3145728 "Optional title"

Reads/writes SITE_ROOT/metadata.json. Optional title from 6th arg or images/<basename>.title file.
Prints key, date, title (tab-separated) newest first.
"""
import json
import os
import re
import sys

TARGET_BYTES = 300 * 1024 * 1024  # 300 MB
METADATA_FILENAME = "metadata.json"
IMAGES_DIR = "images"
THUMBS_DIR = "thumbs"


def slug_to_title(slug: str) -> str:
    """Convert filename slug to human-readable title."""
    if not slug:
        return slug
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    base = re.sub(r"_EN-US[0-9]+", "", base)
    base = re.sub(r"_UHD$", "", base)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced.strip() if spaced else base


def thumb_path(image_path: str) -> str:
    """images/foo.png -> thumbs/foo.png.jpg"""
    base = os.path.basename(image_path)
    return os.path.join(THUMBS_DIR, base + ".jpg")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: update-gallery-metadata.py SITE_ROOT [IMAGE_PATH DATE BYTES]", file=sys.stderr)
        return 1
    site_root = os.path.abspath(sys.argv[1])
    metadata_path = os.path.join(site_root, METADATA_FILENAME)
    images_dir = os.path.join(site_root, IMAGES_DIR)
    thumbs_dir = os.path.join(site_root, THUMBS_DIR)

    # Load existing metadata
    if os.path.isfile(metadata_path):
        with open(metadata_path, "r") as f:
            meta = json.load(f)
    else:
        meta = {}

    # Add new entry if provided
    if len(sys.argv) >= 5:
        image_path = sys.argv[2]
        date_str = sys.argv[3]
        try:
            bytes_val = int(sys.argv[4])
        except ValueError:
            bytes_val = 0
        key = image_path if image_path.startswith("images/") else os.path.join("images", os.path.basename(image_path))
        title = slug_to_title(os.path.basename(key))
        meta[key] = {"date": date_str, "bytes": bytes_val, "title": title}

    # Prune: remove oldest by date until total <= TARGET_BYTES
    total = sum(e["bytes"] for e in meta.values())
    by_date_asc = sorted(meta.items(), key=lambda x: (x[1]["date"], x[0]))
    for key, entry in by_date_asc:
        if total <= TARGET_BYTES:
            break
        path = os.path.join(site_root, key)
        thumb = os.path.join(site_root, thumb_path(key))
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        if os.path.isfile(thumb):
            try:
                os.remove(thumb)
            except OSError:
                pass
        total -= entry["bytes"]
        del meta[key]

    # Always regenerate titles from filename so stale/wrong titles get fixed
    for key in meta:
        meta[key]["title"] = slug_to_title(os.path.basename(key))

    with open(metadata_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Output key, date, title (tab-separated) newest first
    for key in sorted(meta.keys(), key=lambda k: (meta[k]["date"], k), reverse=True):
        date_str = meta[key]["date"]
        title_str = meta[key].get("title") or slug_to_title(os.path.basename(key))
        print(f"{key}\t{date_str}\t{title_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
