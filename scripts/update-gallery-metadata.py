#!/usr/bin/env python3
"""
Update gallery metadata.json: add optional new image, archive oldest when over budget,
output tab-separated lines for building index.html.

When hosted images exceed TARGET_BYTES, the oldest are archived (full-res deleted,
bing_url set) rather than removed. Archived entries stay in the gallery with thumbnails.

Usage:
  python update-gallery-metadata.py SITE_ROOT [IMAGE_PATH DATE BYTES]

Prints key\\tdate\\ttitle\\thref (tab-separated, newest first) to stdout.
"""
import json
import os
import re
import sys

TARGET_BYTES = 860 * 1024 * 1024  # ~860 MB for full-res images
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


def make_bing_url(filename: str) -> str:
    """Reconstruct Bing CDN URL from local filename."""
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"https://www.bing.com/th?id=OHR.{base}.jpg"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: update-gallery-metadata.py SITE_ROOT [IMAGE_PATH DATE BYTES]", file=sys.stderr)
        return 1
    site_root = os.path.abspath(sys.argv[1])
    metadata_path = os.path.join(site_root, METADATA_FILENAME)

    if os.path.isfile(metadata_path):
        with open(metadata_path, "r") as f:
            meta = json.load(f)
    else:
        meta = {}

    if len(sys.argv) >= 5:
        image_path = sys.argv[2]
        date_str = sys.argv[3]
        try:
            bytes_val = int(sys.argv[4])
        except ValueError:
            bytes_val = 0
        key = image_path if image_path.startswith("images/") else os.path.join("images", os.path.basename(image_path))
        meta[key] = {
            "date": date_str,
            "bytes": bytes_val,
            "title": slug_to_title(os.path.basename(key)),
            "archived": False,
        }

    # Correct dates from .date sidecars
    for key in meta:
        date_file = os.path.join(site_root, IMAGES_DIR, os.path.basename(key) + ".date")
        if os.path.isfile(date_file):
            try:
                with open(date_file, "r") as f:
                    sidecar_date = f.read().strip()
                if sidecar_date:
                    meta[key]["date"] = sidecar_date
            except OSError:
                pass

    # Archive oldest hosted images when over budget
    hosted_total = sum(e.get("bytes", 0) for e in meta.values() if not e.get("archived"))
    hosted_by_date = sorted(
        [(k, v) for k, v in meta.items() if not v.get("archived")],
        key=lambda x: (x[1]["date"], x[0]),
    )
    for key, entry in hosted_by_date:
        if hosted_total <= TARGET_BYTES:
            break
        img_path = os.path.join(site_root, key)
        if os.path.isfile(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass
        hosted_total -= entry.get("bytes", 0)
        entry["archived"] = True
        entry["bing_url"] = make_bing_url(os.path.basename(key))
        entry["bytes"] = 0

    # Regenerate titles and ensure bing_url on all archived entries
    for key, entry in meta.items():
        entry["title"] = slug_to_title(os.path.basename(key))
        if entry.get("archived") and "bing_url" not in entry:
            entry["bing_url"] = make_bing_url(os.path.basename(key))

    with open(metadata_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Output: key\tdate\ttitle\thref (newest first)
    for key in sorted(meta.keys(), key=lambda k: (meta[k]["date"], k), reverse=True):
        entry = meta[key]
        href = entry.get("bing_url", key) if entry.get("archived") else key
        print(f"{key}\t{entry['date']}\t{entry['title']}\t{href}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
