#!/usr/bin/env python3
"""
Build and deploy a CDN-backed Bing image-of-the-day gallery to GitHub Pages.

All images (thumbnails + full-res) are served from Bing CDN. Nothing is hosted.
Historical data lives in metadata.json on gh-pages; each run only adds new
entries from the Bing API.

Expected env vars:
  GITHUB_TOKEN          - GitHub token for pushing to gh-pages
  GITHUB_REPOSITORY     - owner/repo (set automatically by GitHub Actions)
  BACKFILL_NPANUHIN     - "true" to run a one-time backfill from npanuhin archive
"""
from collections import defaultdict
import html
import json
import os
import re
import subprocess
import sys
import urllib.request

BING_API_URL = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=8&mkt=en-US"
BING_BASE = "https://www.bing.com"
RES_RE = re.compile(r"_\d+x\d+\.jpg", re.IGNORECASE)
DEPLOY_DIR = "/tmp/gh-pages-deploy"


def repo_url():
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "wallbing-gallery/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def slug_from_bing_url(bing_url):
    if "OHR." not in bing_url:
        return None
    raw = bing_url.split("OHR.", 1)[-1]
    raw = re.split(r"\.(jpg|png)", raw, flags=re.IGNORECASE)[0]
    return raw


THUMB_RE = re.compile(r"(_UHD\.jpg|_\d+x\d+\.jpg)", re.IGNORECASE)

def thumb_url(bing_url):
    return THUMB_RE.sub("_400x240.jpg", bing_url)


def base_name(slug):
    """Strip the locale+ID suffix to get the image name, e.g. 'MayotteCoral'."""
    return re.sub(r"_EN-[A-Z]{2}\d+.*", "", slug)


# ── Clone or init gh-pages ────────────────────────────────────────────────

def clone_gh_pages():
    url = repo_url()
    os.makedirs(DEPLOY_DIR, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", "gh-pages", url, DEPLOY_DIR],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("gh-pages branch not found, will create orphan")
        subprocess.run(["git", "init", DEPLOY_DIR], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", DEPLOY_DIR, "remote", "add", "origin", url],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", DEPLOY_DIR, "checkout", "--orphan", "gh-pages"],
            check=True, capture_output=True,
        )


# ── Load / save metadata ─────────────────────────────────────────────────

def load_metadata():
    path = os.path.join(DEPLOY_DIR, "metadata.json")
    if os.path.isfile(path):
        with open(path) as f:
            entries = json.load(f)
        print(f"Loaded {len(entries)} existing entries from metadata.json")
        return entries
    print("No existing metadata.json, starting fresh")
    return {}


def save_metadata(entries):
    path = os.path.join(DEPLOY_DIR, "metadata.json")
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"Wrote metadata.json ({len(entries)} entries)")


# ── Data sources ──────────────────────────────────────────────────────────

def backfill_npanuhin(entries):
    url = "https://bing.npanuhin.me/US-en.json"
    print("Backfill: fetching npanuhin archive...")
    data = fetch_json(url)
    print(f"  Got {len(data)} total entries from npanuhin")
    count = 0
    for item in data:
        bing_url = item.get("bing_url")
        if not bing_url:
            continue
        bing_url = bing_url.split("&")[0]
        slug = slug_from_bing_url(bing_url)
        if not slug:
            continue
        title = item.get("title", "")
        copyright_text = item.get("copyright", "")
        if copyright_text and not title:
            title = copyright_text.split("(")[0].strip()
        new_entry = {"date": item.get("date", ""), "title": title, "bing_url": bing_url}
        existing = entries.get(slug)
        if not existing or (existing.get("title") or "").replace("_", " ") == slug.replace("_", " "):
            entries[slug] = new_entry
            count += 1
    print(f"  Backfilled {count} entries from npanuhin")


def merge_bing_api(entries):
    print("Fetching Bing API (n=8)...")
    data = fetch_json(BING_API_URL, timeout=30)
    count = 0
    for img in data.get("images", []):
        urlbase = img.get("urlbase", "")
        if "OHR." not in urlbase:
            continue
        url_path = img.get("url", "")
        uhd_url = BING_BASE + RES_RE.sub("_UHD.jpg", url_path)
        slug = slug_from_bing_url(uhd_url)
        if not slug:
            continue
        startdate = img.get("startdate", "")
        date_str = ""
        if startdate and len(startdate) >= 8:
            date_str = f"{startdate[:4]}-{startdate[4:6]}-{startdate[6:8]}"
        copyright_text = img.get("copyright", "")
        title = copyright_text.split("(")[0].strip() if copyright_text else ""
        entries[slug] = {"date": date_str, "title": title, "bing_url": uhd_url}
        count += 1
    print(f"  Merged {count} entries from Bing API")


def dedup(entries):
    """Remove duplicate entries that share the same date and base image name.

    Bing occasionally re-publishes the same photo with a different CDN ID.
    Keep the entry whose slug comes first alphabetically (stable, deterministic).
    """
    groups = defaultdict(list)
    for slug, entry in entries.items():
        key = (entry.get("date", ""), base_name(slug))
        groups[key].append(slug)

    removed = 0
    for (date, bname), slugs in groups.items():
        if len(slugs) <= 1:
            continue
        slugs.sort()
        for dup in slugs[1:]:
            del entries[dup]
            removed += 1
    if removed:
        print(f"  Removed {removed} duplicate entries")


# ── HTML generation ───────────────────────────────────────────────────────

INDEX_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bing wallpapers</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;500;600&display=swap" rel="stylesheet">
  <style>
    :root { --bg: #0f0f12; --card: #1a1a20; --text: #e8e6e3; --muted: #8b8685; --accent: #7c9cbf; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Outfit', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
    .header { padding: 2.5rem 1.5rem 1.5rem; max-width: 1400px; margin: 0 auto; }
    h1 { font-weight: 600; font-size: clamp(1.75rem, 4vw, 2.25rem); letter-spacing: -0.02em; margin: 0 0 0.35rem; }
    .meta { color: var(--muted); font-weight: 300; font-size: 0.95rem; }
    .grid { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 2rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { background: var(--card); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.35); transition: transform 0.2s ease, box-shadow 0.2s ease; }
    .card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.45); }
    .card a { display: block; text-decoration: none; color: inherit; }
    .card img { width: 100%; height: 200px; object-fit: cover; display: block; }
    .card-title { display: block; padding: 0.75rem 1rem 0.15rem; font-size: 0.85rem; font-weight: 500; color: var(--muted); }
    .card-date { display: block; padding: 0 1rem 0.75rem; font-size: 0.75rem; font-weight: 300; color: var(--muted); opacity: 0.9; }
    #lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 100; align-items: center; justify-content: center; padding: 2rem; cursor: pointer; }
    #lightbox.show { display: flex; }
    #lightbox img { max-width: 100%; max-height: 100%; object-fit: contain; border-radius: 8px; }
  </style>
</head>
<body>
  <header class="header">
    <h1>Bing image of the day</h1>
    <p class="meta">New photo each day from Bing. Click any image to view full size.</p>
  </header>
  <div class="grid">
"""

INDEX_TAIL = """\
  </div>
  <div id="lightbox" onclick="this.classList.remove('show')"><img src="" alt=""></div>
  <script>
    document.querySelectorAll('.card a').forEach(function(a) {
      a.addEventListener('click', function(e) {
        var href = this.getAttribute('href');
        if (!href) return;
        e.preventDefault();
        document.getElementById('lightbox').querySelector('img').src = href;
        document.getElementById('lightbox').classList.add('show');
      });
    });
  </script>
</body>
</html>
"""


def build_index(entries):
    sorted_slugs = sorted(
        entries.keys(), key=lambda k: (entries[k]["date"], k), reverse=True
    )
    path = os.path.join(DEPLOY_DIR, "index.html")
    with open(path, "w") as f:
        f.write(INDEX_HEAD)
        for slug in sorted_slugs:
            entry = entries[slug]
            bing_url = entry["bing_url"]
            thumb = thumb_url(bing_url)
            title = html.escape(entry.get("title") or slug)
            date_str = entry.get("date", "")
            f.write(
                f'    <div class="card"><a href="{bing_url}" title="{title}">'
                f'<img src="{thumb}" alt="{title}" loading="lazy">'
                f'<span class="card-title">{title}</span>'
                f'<span class="card-date">{date_str}</span>'
                f"</a></div>\n"
            )
        f.write(INDEX_TAIL)
    print(f"Wrote index.html ({len(sorted_slugs)} cards)")


# ── Git commit + push ─────────────────────────────────────────────────────

def commit_and_push(entries):
    git = lambda *args: subprocess.run(
        ["git", "-C", DEPLOY_DIR] + list(args),
        check=True, capture_output=True, text=True,
    )
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    git("add", "-A")

    diff = subprocess.run(
        ["git", "-C", DEPLOY_DIR, "diff", "--cached", "--stat"],
        capture_output=True, text=True,
    )
    if diff.stdout.strip():
        git("commit", "-m", f"Update gallery: {len(entries)} images")
        git("push", "origin", "gh-pages", "--force")
        print("Pushed to gh-pages")
    else:
        print("No changes to commit")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    clone_gh_pages()
    entries = load_metadata()

    if os.environ.get("BACKFILL_NPANUHIN") == "true":
        backfill_npanuhin(entries)

    merge_bing_api(entries)
    dedup(entries)
    print(f"Total gallery entries: {len(entries)}")

    save_metadata(entries)
    build_index(entries)
    commit_and_push(entries)


if __name__ == "__main__":
    main()
