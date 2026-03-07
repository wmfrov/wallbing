#!/usr/bin/env python3
"""
Read from stdin lines: bytes date_str name (space-separated).
Write SITE_ROOT/metadata.json and print key, date, title (tab-separated, newest-first) to stdout.
"""
import json
import os
import re
import sys


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


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: write-gallery-metadata.py SITE_ROOT")
    deploy = os.path.abspath(sys.argv[1])
    meta = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            bytes_val = int(parts[0])
        except ValueError:
            continue
        date_str, name = parts[1], parts[2]
        key = "images/" + name
        title = slug_to_title(name)
        meta[key] = {"date": date_str, "bytes": bytes_val, "title": title}
    meta_path = os.path.join(deploy, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    for key in meta:
        print(f"{key}\t{meta[key]['date']}\t{meta[key]['title']}")

if __name__ == "__main__":
    main()
