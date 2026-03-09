#!/usr/bin/env python3
"""
Enrich gallery image tags with improved GPT-4o-mini analysis + programmatic color extraction.

One-time backfill script that regenerates all tag fields from scratch using an
enhanced prompt with API description context, and adds programmatic color palettes.

Usage:
  export OPENAI_API_KEY=sk-...
  python3 enrich_tags.py --test 50      # process 50 images for review
  python3 enrich_tags.py                # process all, write local output
  python3 enrich_tags.py --push         # process all, push to gh-pages

Env vars:
  OPENAI_API_KEY       - required
  GITHUB_TOKEN         - required only with --push (CI)
  GITHUB_REPOSITORY    - set automatically by GitHub Actions
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "enrich_progress.json")
THUMB_CACHE = "/tmp/wallbing-thumbs"
THUMB_RE = re.compile(r"(_UHD\.jpg|_\d+x\d+\.jpg)", re.IGNORECASE)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"
MAX_WORKERS = 10
SAVE_EVERY = 50

SUBJECT_VOCAB = [
    "landscape", "mountain", "ocean", "lake", "river", "forest", "desert",
    "cave", "island", "city", "architecture", "bridge", "castle", "ruins",
    "animal", "bird", "flower", "garden", "farm", "snow", "ice", "aurora",
    "two_animals",
]

SYSTEM_PROMPT = f"""\
You are an image tagger for a wallpaper gallery. Analyze the provided image \
and return a JSON object with exactly these fields:

- "subject": array of 1-3 tags from this vocabulary: {json.dumps(SUBJECT_VOCAB)}
  If the image clearly shows exactly two animals, include "two_animals" in \
subject (in addition to "animal" or "bird" as appropriate).
- "season": one of "spring", "summer", "autumn", "winter", or null if unclear
- "country": country name string if identifiable, or null. Use the title and \
background description for clues the image alone may not reveal.
- "region": broader geographic region (e.g. "Southeast Asia", "Scandinavia", \
"Pacific Northwest"), or null
- "time_of_day": one of "dawn", "day", "dusk", "night"
- "mood": one of "serene", "dramatic", "vibrant", "cozy", "mystical", "stark"
- "ai_description": 4-5 sentences describing what you see. Be specific: name \
species, landmarks, geological formations, architectural styles, weather \
phenomena. Mention spatial layout (foreground, background), distinctive \
textures or patterns, and any text or signs visible.
- "keywords": array of 10-20 specific, searchable terms. Include:
  * Specific species and common names (both scientific-sounding and colloquial, \
e.g. "Eurasian lynx", "lynx", "wild cat")
  * Landmark and place names
  * Quantities and groupings ("two", "pair", "flock", "solo")
  * Materials and textures ("cobblestone", "stained glass", "terraced")
  * Activities and states ("flying", "hunting", "blooming", "frozen")
  * Broader category synonyms a user might search for
  * If the image shows an animal, always include the word "animal"
  * If it shows a building, always include "architecture" or "building"
- "search_text": 50-100 words optimized for keyword search. Include synonyms, \
alternate names, related concepts, and terms a user might type into a search box. \
Prioritize breadth of vocabulary over prose quality.

Return ONLY valid JSON, no markdown fences."""


def _ssl_ctx():
    try:
        ctx = ssl.create_default_context()
        urllib.request.urlopen(
            urllib.request.Request("https://api.openai.com", method="HEAD"),
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


# ── Data helpers ──────────────────────────────────────────────────────────


def load_metadata_from_ghpages():
    subprocess.run(
        ["git", "fetch", "origin", "gh-pages"],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    for ref in ("origin/gh-pages", "gh-pages"):
        result = subprocess.run(
            ["git", "show", f"{ref}:metadata.json"],
            capture_output=True, text=True, cwd=SCRIPT_DIR,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    print("ERROR: could not read metadata.json from gh-pages", file=sys.stderr)
    sys.exit(1)


def load_progress():
    if os.path.isfile(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def thumb_url(bing_url):
    return THUMB_RE.sub("_400x240.jpg", bing_url)


# ── Thumbnail cache ──────────────────────────────────────────────────────


def download_thumbnail(bing_url, slug):
    os.makedirs(THUMB_CACHE, exist_ok=True)
    path = os.path.join(THUMB_CACHE, f"{slug}.jpg")
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        with open(path, "rb") as f:
            return f.read()
    url = thumb_url(bing_url)
    req = urllib.request.Request(url, headers={"User-Agent": "wallbing-enrich/1.0"})
    try:
        data = urllib.request.urlopen(req, timeout=15, context=SSL_CTX).read()
        if len(data) > 1024:
            with open(path, "wb") as f:
                f.write(data)
            return data
    except Exception as e:
        print(f"    Thumbnail download failed for {slug}: {e}")
    return None


# ── OpenAI API ────────────────────────────────────────────────────────────


def call_openai(api_key, image_url, title, api_description=None):
    user_parts = [
        {
            "type": "image_url",
            "image_url": {"url": image_url, "detail": "low"},
        },
        {
            "type": "text",
            "text": f"Title: {title}",
        },
    ]
    if api_description:
        user_parts.append({
            "type": "text",
            "text": f"Background description: {api_description}",
        })

    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_parts},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 800,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        OPENAI_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
                resp = json.loads(r.read())
            content = resp["choices"][0]["message"]["content"]
            return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except (json.JSONDecodeError, KeyError, IndexError):
            if attempt < 2:
                time.sleep(1)
                continue
            raise
    return None


def validate_tags(raw):
    if not isinstance(raw, dict):
        return None
    tags = {}
    subj = raw.get("subject", [])
    tags["subject"] = [s for s in subj if s in SUBJECT_VOCAB][:3] if isinstance(subj, list) else []

    for field in ("season", "country", "region", "time_of_day", "mood", "ai_description", "search_text"):
        val = raw.get(field)
        tags[field] = val if isinstance(val, str) else None

    kw = raw.get("keywords", [])
    tags["keywords"] = [str(k) for k in kw][:20] if isinstance(kw, list) else []

    return tags


# ── gh-pages push ─────────────────────────────────────────────────────────


def push_to_ghpages(metadata):
    deploy = "/tmp/gh-pages-enrich-deploy"

    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GITHUB_TOKEN / GITHUB_REPOSITORY not set, skipping push")
        return

    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    os.makedirs(deploy, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", "gh-pages", url, deploy],
        check=True, capture_output=True, text=True,
    )

    with open(os.path.join(deploy, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    sys.path.insert(0, SCRIPT_DIR)
    import build_gallery
    old_deploy = build_gallery.DEPLOY_DIR
    build_gallery.DEPLOY_DIR = deploy
    build_gallery.build_index(metadata)
    build_gallery.build_search_index(metadata)
    build_gallery.DEPLOY_DIR = old_deploy

    git = lambda *a: subprocess.run(
        ["git", "-C", deploy] + list(a), check=True, capture_output=True, text=True,
    )
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "-A")
    diff = subprocess.run(
        ["git", "-C", deploy, "diff", "--cached", "--stat"],
        capture_output=True, text=True,
    )
    if diff.stdout.strip():
        enriched = sum(1 for e in metadata.values() if e.get("tags", {}).get("keywords"))
        git("commit", "-m", f"Enrich tags: {enriched}/{len(metadata)} enriched")
        git("push", "origin", "gh-pages", "--force")
        print("Pushed to gh-pages")
    else:
        print("No changes to push")


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY not set")
        sys.exit(1)

    do_push = "--push" in sys.argv
    test_limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--test" and i + 1 < len(sys.argv):
            test_limit = int(sys.argv[i + 1])

    print("Loading metadata from gh-pages...")
    metadata = load_metadata_from_ghpages()
    print(f"  {len(metadata)} entries")

    progress = load_progress()
    print(f"  {len(progress)} entries already enriched in progress cache")

    for slug, cached_tags in progress.items():
        if slug in metadata:
            metadata[slug]["tags"] = cached_tags

    to_process = []
    for slug, entry in metadata.items():
        tags = entry.get("tags", {})
        if not tags.get("keywords"):
            to_process.append((slug, entry))

    if test_limit:
        to_process = to_process[:test_limit]

    print(f"  {len(to_process)} entries to enrich")
    if not to_process:
        print("Nothing to do.")
        if do_push:
            push_to_ghpages(metadata)
        return

    from color_extract import extract_palette

    print("Downloading thumbnails...")
    thumb_data = {}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(download_thumbnail, entry["bing_url"], slug): slug
            for slug, entry in to_process
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                data = fut.result()
                if data:
                    thumb_data[slug] = data
            except Exception as e:
                print(f"  Thumbnail error {slug}: {e}")
    print(f"  {len(thumb_data)} thumbnails ready")

    print("Extracting colors...")
    color_palettes = {}
    for slug, data in thumb_data.items():
        try:
            color_palettes[slug] = extract_palette(data)
        except Exception as e:
            print(f"  Color error {slug}: {e}")
    print(f"  {len(color_palettes)} palettes extracted")

    print("Tagging with GPT-4o-mini...")
    completed = 0
    failed = 0

    def _tag_one(slug_entry):
        slug, entry = slug_entry
        thumb = thumb_url(entry["bing_url"])
        title = entry.get("title") or slug
        api_desc = entry.get("description")
        return slug, call_openai(api_key, thumb, title, api_desc)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_tag_one, item): item for item in to_process}
        for fut in as_completed(futures):
            slug, entry = futures[fut]
            try:
                s, raw_tags = fut.result()
                tags = validate_tags(raw_tags)
                if tags:
                    tags["color_palette"] = color_palettes.get(slug, [])
                    metadata[slug]["tags"] = tags
                    progress[slug] = tags
                    completed += 1
                else:
                    failed += 1
                    print(f"  INVALID response for {slug}")
            except Exception as exc:
                failed += 1
                print(f"  ERROR tagging {slug}: {exc}")

            total_done = completed + failed
            if total_done % SAVE_EVERY == 0:
                save_progress(progress)
                print(f"  Progress: {total_done}/{len(to_process)} "
                      f"({completed} ok, {failed} failed)")

    save_progress(progress)
    enriched_total = sum(1 for e in metadata.values() if e.get("tags", {}).get("keywords"))
    print(f"\nDone: {completed} newly enriched, {failed} failed")
    print(f"Total enriched: {enriched_total}/{len(metadata)}")

    if do_push:
        push_to_ghpages(metadata)
    else:
        out = os.path.join(SCRIPT_DIR, "metadata_enriched.json")
        with open(out, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
