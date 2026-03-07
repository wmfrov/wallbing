#!/usr/bin/env python3
"""
Read from stdin lines: bytes date_str name (space-separated).
Write SITE_ROOT/metadata.json and print image paths (newest-first order) to stdout.
Used by upload-local-images-to-pages.sh to build metadata from local selection.
"""
import json
import os
import sys

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
        meta[key] = {"date": date_str, "bytes": bytes_val}
    meta_path = os.path.join(deploy, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    for key in meta:
        print(key)

if __name__ == "__main__":
    main()
