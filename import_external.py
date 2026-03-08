#!/usr/bin/env python3
"""
One-time migration: merge external.json + niumoo CDN slug data into metadata.json.

Reads the current metadata.json from the gh-pages branch, enriches existing entries
with description/caption/subtitle from external.json, and adds new entries for dates
where a valid Bing CDN URL can be resolved.  All new entries are HEAD-validated to
reject dummy 1192-byte placeholder images.

NOTE: niumoo and external.json (npanuhin) have a ~1-day date offset for early entries.
This script uses niumoo's own dates and titles for niumoo-sourced entries, and matches
external.json enrichment data by title to bridge the gap.

Output: metadata_import.json in the working directory.
"""

import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTERNAL_JSON = os.path.join(SCRIPT_DIR, "external.json")
OUTPUT_JSON = os.path.join(SCRIPT_DIR, "metadata_import.json")
NIUMOO_URL = "https://raw.githubusercontent.com/niumoo/bing-wallpaper/main/bing-wallpaper.md"

LOCALE_RE = re.compile(r"_[A-Z]{2}-[A-Z]{2}\d+|_ROW\d+")
NIUMOO_LINE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*\|\s*\[(.+?)\s*\(©"
    r".*?OHR\.(\w+?_EN-[A-Z]{2}\d+)_UHD\.jpg"
)
DUMMY_SIZE_THRESHOLD = 2000
MAX_WORKERS = 10
ENRICHMENT_FIELDS = ("description", "caption", "subtitle")


def _ssl_ctx():
    """Best-effort SSL context: tries system certs, then certifi, then unverified."""
    try:
        ctx = ssl.create_default_context()
        urllib.request.urlopen(
            urllib.request.Request("https://www.bing.com", method="HEAD"),
            timeout=5, context=ctx,
        )
        return ctx
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


SSL_CTX = _ssl_ctx()


# ── Data loading ──────────────────────────────────────────────────────────


def load_metadata_from_ghpages():
    result = subprocess.run(
        ["git", "show", "gh-pages:metadata.json"],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print("ERROR: could not read metadata.json from gh-pages", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def load_external():
    with open(EXTERNAL_JSON) as f:
        return json.load(f)


def fetch_niumoo():
    """Fetch niumoo bing-wallpaper.md and return {date: (slug, title)} for EN-US."""
    print("  Downloading from GitHub...")
    req = urllib.request.Request(NIUMOO_URL, headers={"User-Agent": "wallbing-import/1.0"})
    with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
        text = r.read().decode("utf-8")

    entries = {}
    for line in text.splitlines():
        m = NIUMOO_LINE_RE.search(line)
        if m:
            date, title, slug = m.group(1), m.group(2).strip(), m.group(3)
            entries[date] = (slug, title)
    return entries


# ── URL helpers ───────────────────────────────────────────────────────────


def normalize_bing_url(raw_url):
    """Return canonical ``https://www.bing.com/th?id=OHR.{slug}_UHD.jpg`` or None."""
    if not raw_url or "OHR." not in raw_url:
        return None
    after_ohr = raw_url.split("OHR.", 1)[-1]
    base = re.split(r"\.(jpg|png)", after_ohr, flags=re.IGNORECASE)[0]
    if not LOCALE_RE.search(base):
        return None
    if not base.endswith("_UHD"):
        base += "_UHD"
    return f"https://www.bing.com/th?id=OHR.{base}.jpg"


def slug_from_url(url):
    """Extract the metadata-key slug (e.g. ``FooBar_EN-US123_UHD``) from a Bing CDN URL."""
    if not url or "OHR." not in url:
        return None
    raw = url.split("OHR.", 1)[-1]
    raw = re.split(r"\.(jpg|png)", raw, flags=re.IGNORECASE)[0]
    if not LOCALE_RE.search(raw):
        return None
    return raw


def make_bing_url(slug):
    """Build a canonical CDN URL from a niumoo-style slug (without _UHD)."""
    return f"https://www.bing.com/th?id=OHR.{slug}_UHD.jpg"


# ── Validation ────────────────────────────────────────────────────────────


def head_check(url, timeout=15):
    """Return Content-Length for *url*, or -1 on any error."""
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "wallbing-import/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            return int(r.headers.get("Content-Length", "0"))
    except Exception:
        return -1


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    # ── 1. Load all data sources ──────────────────────────────────────────
    print("Loading metadata.json from gh-pages...")
    metadata = load_metadata_from_ghpages()
    print(f"  {len(metadata)} existing entries")

    print("Loading external.json...")
    external = load_external()
    print(f"  {len(external)} external entries")

    print("Fetching niumoo slug data...")
    niumoo = fetch_niumoo()
    print(f"  {len(niumoo)} EN-US entries parsed")

    # ── 2. Build lookups ──────────────────────────────────────────────────
    existing_dates = set()
    for entry in metadata.values():
        d = entry.get("date", "")
        if d:
            existing_dates.add(d)

    # external.json title -> ext entry (for enrichment by title match)
    ext_by_title: dict[str, dict] = {}
    for ext in external:
        t = ext.get("title", "")
        if t:
            ext_by_title[t] = ext

    # ── 3. Enrich existing entries from external.json ─────────────────────
    # Match by date (works reliably for the 2023+ range where external has data)
    ext_by_date = {e["date"]: e for e in external}
    enriched = 0
    for slug, entry in metadata.items():
        d = entry.get("date", "")
        ext = ext_by_date.get(d)
        if not ext:
            continue
        changed = False
        for field in ENRICHMENT_FIELDS:
            val = ext.get(field)
            if val and field not in entry:
                entry[field] = val
                changed = True
        if changed:
            enriched += 1

    print(f"\nEnriched {enriched} existing entries with descriptions")

    # ── 4. Collect candidates for new entries ─────────────────────────────
    #
    # Source A: external.json entries with bing_url not already in metadata
    # Source B: niumoo entries for dates not in metadata and not in Source A
    #
    # For Source B, use niumoo's own date + title (avoids the ~1-day offset
    # between niumoo and external.json).

    candidates = []  # (date, title, cdn_url, enrichment_ext_or_None)

    # Source A: external.json entries with bing_url
    ext_dates_added = set()
    for ext in external:
        if not ext.get("bing_url"):
            continue
        cdn_url = normalize_bing_url(ext["bing_url"])
        if not cdn_url:
            continue
        date = ext["date"]
        if date in existing_dates:
            continue
        candidates.append((date, ext.get("title", ""), cdn_url, ext))
        ext_dates_added.add(date)

    # Source B: niumoo entries for remaining gaps
    skipped_already_covered = 0
    for ndate, (nslug, ntitle) in niumoo.items():
        if ndate in existing_dates or ndate in ext_dates_added:
            skipped_already_covered += 1
            continue
        cdn_url = make_bing_url(nslug)
        # Try to find enrichment data from external.json by title match
        ext = ext_by_title.get(ntitle)
        candidates.append((ndate, ntitle, cdn_url, ext))

    print(f"Candidates to validate: {len(candidates)}")
    print(f"  From external.json bing_url: {len(ext_dates_added)}")
    print(f"  From niumoo slugs: {len(candidates) - len(ext_dates_added)}")

    # ── 5. HEAD-validate candidate URLs in parallel ───────────────────────
    if not candidates:
        print("\nNo candidates to validate.")
    else:
        print(f"\nHEAD-checking {len(candidates)} URLs ({MAX_WORKERS} threads)...")

    valid = []
    rejected_count = 0
    rejected_samples = []

    def _check(item):
        return item, head_check(item[2])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_check, c) for c in candidates]
        for i, fut in enumerate(as_completed(futures), 1):
            item, size = fut.result()
            if size > DUMMY_SIZE_THRESHOLD:
                valid.append(item)
            else:
                rejected_count += 1
                date, title = item[0], item[1]
                if len(rejected_samples) < 15:
                    rejected_samples.append(f"  {date} | {title[:50]} | size={size}")
            if i % 100 == 0:
                print(f"  ...checked {i}/{len(candidates)}")

    print(f"\n  Passed validation: {len(valid)}")
    print(f"  Rejected (dummy/dead): {rejected_count}")
    if rejected_samples:
        print("  Sample rejections:")
        for line in rejected_samples:
            print(line)

    # ── 6. Merge validated entries into metadata ──────────────────────────
    added = 0
    for date, title, cdn_url, ext in valid:
        slug = slug_from_url(cdn_url)
        if not slug or slug in metadata:
            continue

        entry = {"date": date, "title": title, "bing_url": cdn_url}
        if ext:
            for field in ENRICHMENT_FIELDS:
                val = ext.get(field)
                if val:
                    entry[field] = val
        metadata[slug] = entry
        added += 1

    print(f"\nAdded {added} new entries to metadata")
    print(f"Total entries: {len(metadata)}")

    # ── 7. Write output ───────────────────────────────────────────────────
    with open(OUTPUT_JSON, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nWrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
