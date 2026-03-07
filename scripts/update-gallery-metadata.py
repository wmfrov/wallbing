#!/usr/bin/env python3
"""
Update gallery metadata.json and output tab-separated lines for building index.html.
All images link to Bing CDN for full-res viewing.

Usage:
  python update-gallery-metadata.py SITE_ROOT [SLUG DATE TITLE]

  SLUG  = image slug, e.g. BrockenSunrise_EN-US8849518575_UHD
  DATE  = YYYY-MM-DD
  TITLE = human-readable title (optional; falls back to slug-derived title)

Prints slug\\tdate\\ttitle\\tbing_url\\tthumb (tab-separated, newest first) to stdout.
"""
import json
import os
import re
import sys

METADATA_FILENAME = "metadata.json"
THUMBS_DIR = "thumbs"


def slug_to_title(slug: str) -> str:
    if not slug:
        return slug
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    base = re.sub(r"_EN-US[0-9]+", "", base)
    base = re.sub(r"_UHD$", "", base)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced.strip() if spaced else base


def make_bing_url(slug: str) -> str:
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    return f"https://www.bing.com/th?id=OHR.{base}.jpg"


def thumb_name(slug: str) -> str:
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    if base.endswith("_UHD"):
        base = base[:-4]
    return base + ".jpg"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: update-gallery-metadata.py SITE_ROOT [SLUG DATE TITLE]", file=sys.stderr)
        return 1

    site_root = os.path.abspath(sys.argv[1])
    metadata_path = os.path.join(site_root, METADATA_FILENAME)

    if os.path.isfile(metadata_path):
        with open(metadata_path, "r") as f:
            meta = json.load(f)
    else:
        meta = {}

    if len(sys.argv) >= 4:
        slug = sys.argv[2]
        date_str = sys.argv[3]
        title = sys.argv[4] if len(sys.argv) >= 5 else slug_to_title(slug)
        meta[slug] = {
            "date": date_str,
            "title": title,
            "bing_url": make_bing_url(slug),
        }

    for slug in meta:
        if "bing_url" not in meta[slug]:
            meta[slug]["bing_url"] = make_bing_url(slug)
        if "title" not in meta[slug]:
            meta[slug]["title"] = slug_to_title(slug)

    with open(metadata_path, "w") as f:
        json.dump(meta, f, indent=2)

    for slug in sorted(meta.keys(), key=lambda k: (meta[k].get("date", ""), k), reverse=True):
        entry = meta[slug]
        thumb = THUMBS_DIR + "/" + thumb_name(slug)
        print(f"{slug}\t{entry['date']}\t{entry['title']}\t{entry['bing_url']}\t{thumb}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
