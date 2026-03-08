#!/usr/bin/env python3
"""
Tag gallery images using GPT-4o-mini vision analysis.

Reads metadata.json from gh-pages, sends untagged thumbnails to the OpenAI
API, and writes structured tags (subject, colors, season, country,
time_of_day, mood, ai_description) back into metadata.json.

Progress is cached in tags_progress.json so the backfill can be resumed
after interruptions.

Usage:
  export OPENAI_API_KEY=sk-...
  python3 tag_images.py           # writes metadata locally
  python3 tag_images.py --push    # also pushes updated gh-pages

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
PROGRESS_FILE = os.path.join(SCRIPT_DIR, "tags_progress.json")
THUMB_RE = re.compile(r"(_UHD\.jpg|_\d+x\d+\.jpg)", re.IGNORECASE)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"
MAX_WORKERS = 10
SAVE_EVERY = 50

SUBJECT_VOCAB = [
    "landscape", "mountain", "ocean", "lake", "river", "forest", "desert",
    "cave", "island", "city", "architecture", "bridge", "castle", "ruins",
    "animal", "bird", "flower", "garden", "farm", "snow", "ice", "aurora",
]

SYSTEM_PROMPT = f"""\
You are an image tagger for a wallpaper gallery. Analyze the provided image \
and return a JSON object with exactly these fields:

- "subject": array of 1-3 tags from this vocabulary: {json.dumps(SUBJECT_VOCAB)}
- "colors": array of 2-3 dominant color names (e.g. "deep blue", "golden", "emerald green")
- "season": one of "spring", "summer", "autumn", "winter", or null if unclear
- "country": country name string if identifiable, or null
- "time_of_day": one of "dawn", "day", "dusk", "night"
- "mood": one of "serene", "dramatic", "vibrant", "cozy", "mystical", "stark"
- "ai_description": 2-3 sentences describing what you see. Be specific: name \
species, landmarks, geological formations, architectural styles, weather \
phenomena. Mention spatial layout (foreground, background), distinctive \
textures or patterns, and any text or signs visible. Maximize distinctive, \
searchable detail.

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
    result = subprocess.run(
        ["git", "show", "gh-pages:metadata.json"],
        capture_output=True, text=True, cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print("ERROR: could not read metadata.json from gh-pages", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


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


# ── OpenAI API ────────────────────────────────────────────────────────────


def call_openai(api_key, image_url, title):
    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": image_url, "detail": "low"},
        },
        {
            "type": "text",
            "text": f"Title: {title}",
        },
    ]

    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 400,
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
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
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
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            if attempt < 2:
                time.sleep(1)
                continue
            raise
    return None


VALID_FIELDS = {"subject", "colors", "season", "country", "time_of_day", "mood", "ai_description"}


def validate_tags(raw):
    """Ensure the response has the expected shape; return cleaned dict or None."""
    if not isinstance(raw, dict):
        return None
    tags = {}
    subj = raw.get("subject", [])
    if isinstance(subj, list):
        tags["subject"] = [s for s in subj if s in SUBJECT_VOCAB][:3]
    else:
        tags["subject"] = []
    colors = raw.get("colors", [])
    tags["colors"] = colors[:3] if isinstance(colors, list) else []
    for field in ("season", "country", "time_of_day", "mood", "ai_description"):
        val = raw.get(field)
        tags[field] = val if isinstance(val, str) else None
    return tags


# ── gh-pages push ─────────────────────────────────────────────────────────


def push_to_ghpages(metadata):
    """Checkout gh-pages worktree, write metadata + rebuild HTML, commit, push."""
    deploy = "/tmp/gh-pages-tag-deploy"

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
        tagged = sum(1 for e in metadata.values() if "tags" in e)
        git("commit", "-m", f"Tag images: {tagged}/{len(metadata)} tagged")
        git("push", "origin", "gh-pages", "--force")
        print("Pushed to gh-pages")
    else:
        print("No changes to push")


# ── Main ──────────────────────────────────────────────────────────────────


def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY not set, skipping tagging")
        return

    do_push = "--push" in sys.argv

    print("Loading metadata from gh-pages...")
    metadata = load_metadata_from_ghpages()
    print(f"  {len(metadata)} entries")

    progress = load_progress()
    print(f"  {len(progress)} entries already tagged in progress cache")

    # Apply cached progress into metadata
    for slug, tags in progress.items():
        if slug in metadata:
            metadata[slug]["tags"] = tags

    # Find entries that still need tagging
    to_tag = []
    for slug, entry in metadata.items():
        if "tags" not in entry:
            to_tag.append((slug, entry))

    print(f"  {len(to_tag)} entries need tagging")
    if not to_tag:
        print("Nothing to do.")
        if do_push:
            push_to_ghpages(metadata)
        return

    # Tag in parallel
    completed = 0
    failed = 0

    def _tag_one(slug_entry):
        slug, entry = slug_entry
        thumb = thumb_url(entry["bing_url"])
        title = entry.get("title") or slug
        return slug, call_openai(api_key, thumb, title)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_tag_one, item): item for item in to_tag}
        for fut in as_completed(futures):
            slug, entry = futures[fut]
            try:
                s, raw_tags = fut.result()
                tags = validate_tags(raw_tags)
                if tags:
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
                print(f"  Progress: {total_done}/{len(to_tag)} "
                      f"({completed} ok, {failed} failed)")

    save_progress(progress)
    tagged_total = sum(1 for e in metadata.values() if "tags" in e)
    print(f"\nDone: {completed} newly tagged, {failed} failed")
    print(f"Total tagged: {tagged_total}/{len(metadata)}")

    if do_push:
        push_to_ghpages(metadata)
    else:
        out = os.path.join(SCRIPT_DIR, "metadata_tagged.json")
        with open(out, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()
