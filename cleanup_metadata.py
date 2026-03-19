#!/usr/bin/env python3
"""
One-time cleanup of metadata.json anomalies.

Reads metadata.json from the current directory (expects gh-pages checkout),
applies fixes, and writes it back.

Groups:
  1. 2021-09-24 cluster: salvage 7 contaminated entries, remove 1 duplicate
  2. LittleBirds_ROW: remove locale variant
  3. Null titles (2025-11-01..06): derive from slug
  4. Dirty URLs (2026-02-28..03-08): strip trailing query params
"""

import json
import re
import sys

METADATA_PATH = "metadata.json"

# Group 1: 2021-09-24 — salvage these (clear description, subtitle, delete tags)
SALVAGE_SLUGS = [
    "BabyRhino_EN-US4289854732_UHD",
    "BenagilCave_EN-US2996856855_UHD",
    "BlackSun_EN-US3611441755_UHD",
    "Firefox_EN-US3200029768_UHD",
    "LeCastella_EN-US3410369495_UHD",
    "PicoThorn_DE-DE6861243194_UHD",
    "RisingMoon_EN-US3728383001_UHD",
]

# Group 1+2: remove these entirely
REMOVE_SLUGS = [
    "PorkiesTrail_EN-GB3300570376_UHD",  # duplicate of EN-US on 2021-09-26
    "LittleBirds_ROW5989976879_UHD",     # ROW locale variant
]

# Group 3: null titles — derive from slug base name
NULL_TITLE_MAP = {
    "BisonSprings_EN-US6080228013_UHD": "Bison Springs",
    "KyotoMaple_EN-US6732403492_UHD": "Kyoto Maple",
    "MexicoJelly_EN-US6803524310_UHD": "Mexico Jelly",
    "TowerBridgeUK_EN-US6871236865_UHD": "Tower Bridge UK",
    "MoncayoAutumn_EN-US1753631441_UHD": "Moncayo Autumn",
    "LanternsThailand_EN-US6955074347_UHD": "Lanterns Thailand",
}


def clean_url(url):
    """Strip anything after .jpg (e.g. &rf=LaDigue_UHD.jpg&pid=hp)."""
    idx = url.find(".jpg")
    if idx == -1:
        return url
    return url[:idx + 4]


def main():
    with open(METADATA_PATH) as f:
        meta = json.load(f)
    print(f"Loaded {len(meta)} entries")

    # Group 1: Remove entries
    removed = []
    for slug in REMOVE_SLUGS:
        if slug in meta:
            del meta[slug]
            removed.append(slug)
    print(f"\nRemoved {len(removed)} entries:")
    for s in removed:
        print(f"  - {s}")

    # Group 1: Salvage contaminated 2021-09-24 entries
    salvaged = []
    for slug in SALVAGE_SLUGS:
        if slug not in meta:
            print(f"  WARNING: {slug} not found, skipping")
            continue
        entry = meta[slug]
        entry["description"] = ""
        entry["subtitle"] = ""
        entry.pop("tags", None)
        # Fix PicoThorn mangled title
        if slug == "PicoThorn_DE-DE6861243194_UHD":
            entry["title"] = "Pico Thorn"
        salvaged.append(slug)
    print(f"\nSalvaged {len(salvaged)} entries (cleared description/subtitle/tags):")
    for s in salvaged:
        print(f"  - {s} → title: {meta[s]['title']}")

    # Group 3: Fix null titles
    fixed_titles = []
    for slug, title in NULL_TITLE_MAP.items():
        if slug not in meta:
            print(f"  WARNING: {slug} not found, skipping")
            continue
        meta[slug]["title"] = title
        fixed_titles.append(slug)
    print(f"\nFixed {len(fixed_titles)} null titles:")
    for s in fixed_titles:
        print(f"  - {s} → {meta[s]['title']}")

    # Group 4: Clean dirty URLs
    cleaned_urls = []
    for slug, entry in meta.items():
        url = entry.get("bing_url", "")
        if "&rf=" in url or "&pid=" in url:
            entry["bing_url"] = clean_url(url)
            cleaned_urls.append(slug)
    print(f"\nCleaned {len(cleaned_urls)} dirty URLs:")
    for s in cleaned_urls:
        print(f"  - {s}")

    # Write back
    with open(METADATA_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nWrote {len(meta)} entries to {METADATA_PATH}")


if __name__ == "__main__":
    main()
