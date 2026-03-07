#!/usr/bin/env python3
"""
Update gallery metadata.json: add optional new image, prune to target size (FIFO by date),
output image paths newest-first for building index.html.

Usage:
  python update-gallery-metadata.py SITE_ROOT [IMAGE_PATH DATE BYTES]
  e.g. python update-gallery-metadata.py . images/Photo.png 2025-03-06 3145728

Reads/writes SITE_ROOT/metadata.json. Prunes by removing oldest-by-date until total <= TARGET_BYTES.
Prints one image path per line (newest first) to stdout for index generation.
"""
import json
import os
import sys

TARGET_BYTES = 300 * 1024 * 1024  # 300 MB
METADATA_FILENAME = "metadata.json"
IMAGES_DIR = "images"
THUMBS_DIR = "thumbs"


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
        meta[key] = {"date": date_str, "bytes": bytes_val}

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

    with open(metadata_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Output image paths newest first (for index.html)
    for key in sorted(meta.keys(), key=lambda k: (meta[k]["date"], k), reverse=True):
        print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
