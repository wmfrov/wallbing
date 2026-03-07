#!/usr/bin/env python3
"""
Read from stdin lines: bytes date_str status name (space-separated).
  status = "hosted" or "archived"
Write SITE_ROOT/metadata.json and print key\\tdate\\ttitle\\thref\\tthumb (newest-first) to stdout.
Used by upload-local-images-to-pages.sh to build metadata from local selection.
"""
import json
import os
import re
import sys

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


def thumb_name(filename: str) -> str:
    """Image filename -> clean thumbnail name: strip _UHD and extension, add .jpg."""
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    if base.endswith("_UHD"):
        base = base[:-4]
    return base + ".jpg"


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: write-gallery-metadata.py SITE_ROOT")
    deploy = os.path.abspath(sys.argv[1])
    meta = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            bytes_val = int(parts[0])
        except ValueError:
            continue
        date_str, status, name = parts[1], parts[2], parts[3]
        key = "images/" + name
        is_archived = (status == "archived")
        title = slug_to_title(name)
        entry = {
            "date": date_str,
            "bytes": 0 if is_archived else bytes_val,
            "title": title,
            "archived": is_archived,
        }
        if is_archived:
            entry["bing_url"] = make_bing_url(name)
        meta[key] = entry

    meta_path = os.path.join(deploy, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    for key in sorted(meta.keys(), key=lambda k: (meta[k]["date"], k), reverse=True):
        entry = meta[key]
        href = entry.get("bing_url", key) if entry.get("archived") else key
        thumb = THUMBS_DIR + "/" + thumb_name(os.path.basename(key))
        print(f"{key}\t{entry['date']}\t{entry['title']}\t{href}\t{thumb}")


if __name__ == "__main__":
    main()
