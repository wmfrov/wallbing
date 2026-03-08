#!/usr/bin/env python3
"""
Build and deploy a CDN-backed Bing image-of-the-day gallery to GitHub Pages.

All images (thumbnails + full-res) are served from Bing CDN. Nothing is hosted.
Historical data lives in metadata.json on gh-pages; each run only adds new
entries from the Bing API.

Expected env vars:
  GITHUB_TOKEN          - GitHub token for pushing to gh-pages
  GITHUB_REPOSITORY     - owner/repo (set automatically by GitHub Actions)
"""
from collections import defaultdict
import html
import json
import os
import re
import subprocess
import urllib.request

BING_API_URL = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=8&mkt=en-US"
BING_BASE = "https://www.bing.com"
RES_RE = re.compile(r"_\d+x\d+\.jpg", re.IGNORECASE)
LOCALE_RE = re.compile(r"_[A-Z]{2}-[A-Z]{2}\d+|_ROW\d+")
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
    if not LOCALE_RE.search(raw):
        return None
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


def purge_invalid(entries):
    """Remove entries whose slug lacks a valid locale pattern."""
    invalid = [s for s in entries if not LOCALE_RE.search(s)]
    for s in invalid:
        del entries[s]
    if invalid:
        print(f"  Purged {len(invalid)} entries with invalid slugs")


def save_metadata(entries):
    path = os.path.join(DEPLOY_DIR, "metadata.json")
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"Wrote metadata.json ({len(entries)} entries)")


# ── Data sources ──────────────────────────────────────────────────────────

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
        if slug in entries:
            entries[slug].update({"date": date_str, "title": title, "bing_url": uhd_url})
        else:
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
    :root { --bg: #0f0f12; --card: #1a1a20; --text: #e8e6e3; --muted: #8b8685; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Outfit', system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
    .header { padding: 2.5rem 1.5rem 1.5rem; max-width: 1400px; margin: 0 auto; }
    h1 { font-weight: 600; font-size: clamp(1.75rem, 4vw, 2.25rem); letter-spacing: -0.02em; margin: 0 0 0.35rem; }
    .meta { color: var(--muted); font-weight: 300; font-size: 0.95rem; }
    .search-wrap { margin-top: 1rem; }
    .search-wrap input { width: 100%; max-width: 400px; padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #333; background: var(--card); color: var(--text); font-family: inherit; font-size: 0.9rem; outline: none; transition: border-color 0.2s; }
    .search-wrap input::placeholder { color: var(--muted); }
    .search-wrap input:focus { border-color: #555; }
    .filters { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 1rem; display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
    .filter-pill { padding: 0.35rem 0.75rem; border-radius: 20px; border: 1px solid #333; background: transparent; color: var(--muted); font-family: inherit; font-size: 0.75rem; font-weight: 500; cursor: pointer; transition: all 0.2s; text-transform: capitalize; }
    .filter-pill:hover { border-color: #555; color: var(--text); }
    .filter-pill.active { background: rgba(255,255,255,0.12); border-color: #666; color: var(--text); }
    .filter-clear { padding: 0.35rem 0.75rem; border-radius: 20px; border: 1px solid transparent; background: none; color: var(--muted); font-family: inherit; font-size: 0.75rem; cursor: pointer; opacity: 0; pointer-events: none; transition: opacity 0.2s; }
    .filter-clear.show { opacity: 1; pointer-events: auto; }
    .filter-clear:hover { color: var(--text); }
    .header-link { color: inherit; text-decoration: none; }
    .header-link:hover { text-decoration: underline; }
    .filter-label { color: var(--muted); font-size: 0.75rem; font-weight: 500; margin-right: 0.25rem; }
    .grid { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 2rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { background: var(--card); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.35); transition: transform 0.2s ease, box-shadow 0.2s ease; }
    .card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.45); }
    .card a { display: block; text-decoration: none; color: inherit; }
    .card img { width: 100%; height: 200px; object-fit: cover; display: block; }
    .card-title { display: block; padding: 0.75rem 1rem 0.15rem; font-size: 0.85rem; font-weight: 500; color: var(--muted); }
    .card-date { display: block; padding: 0 1rem 0.15rem; font-size: 0.75rem; font-weight: 300; color: var(--muted); opacity: 0.9; }
    .card-tags { display: flex; flex-wrap: wrap; gap: 0.25rem; padding: 0 1rem 0.75rem; }
    .card-tag { font-size: 0.6rem; padding: 0.15rem 0.45rem; border-radius: 10px; background: rgba(255,255,255,0.07); color: var(--muted); text-transform: capitalize; }
    #lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 100; flex-direction: column; align-items: center; justify-content: center; padding: 2rem; }
    #lightbox.show { display: flex; }
    .lb-main { display: flex; align-items: center; gap: 1rem; max-width: 100%; max-height: calc(100vh - 8rem); }
    .lb-nav { background: none; border: none; color: rgba(255,255,255,0.7); font-size: 2.5rem; cursor: pointer; padding: 0.5rem; line-height: 1; user-select: none; transition: color 0.2s; flex-shrink: 0; }
    .lb-nav:hover { color: #fff; }
    #lightbox img { max-width: calc(100vw - 10rem); max-height: calc(100vh - 10rem); object-fit: contain; border-radius: 8px; }
    .lb-info { text-align: center; margin-top: 1rem; }
    .lb-title { font-size: 1rem; font-weight: 500; }
    .lb-date { font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; }
    .lb-download { display: inline-block; margin-top: 0.5rem; padding: 0.4rem 1rem; border-radius: 6px; background: rgba(255,255,255,0.12); color: var(--text); text-decoration: none; font-size: 0.8rem; font-weight: 500; transition: background 0.2s; }
    .lb-download:hover { background: rgba(255,255,255,0.22); }
    .lb-close { position: absolute; top: 1rem; right: 1.5rem; background: none; border: none; color: rgba(255,255,255,0.7); font-size: 2rem; cursor: pointer; line-height: 1; transition: color 0.2s; }
    .lb-close:hover { color: #fff; }
  </style>
</head>
<body>
  <header class="header">
    <h1><a href="/" class="header-link">Bing image of the day</a></h1>
    <p class="meta">New photo each day from Bing. Click any image to view full size.</p>
    <div class="search-wrap"><input type="text" id="search" placeholder="Loading search\u2026" autocomplete="off" disabled aria-label="Search images"></div>
  </header>
  <div class="filters" id="filters"></div>
  <div class="grid">
"""

INDEX_TAIL = """\
  </div>
  <div id="lightbox">
    <button class="lb-close" aria-label="Close">&times;</button>
    <div class="lb-main">
      <button class="lb-nav" id="lb-prev" aria-label="Previous">&#8249;</button>
      <img src="" alt="">
      <button class="lb-nav" id="lb-next" aria-label="Next">&#8250;</button>
    </div>
    <div class="lb-info">
      <div class="lb-title"></div>
      <div class="lb-date"></div>
      <a class="lb-download" href="#" download target="_blank">&#x2193; Download UHD</a>
    </div>
  </div>
  <script>
    (function() {
      var lb = document.getElementById('lightbox');
      var lbImg = lb.querySelector('img');
      var lbTitle = lb.querySelector('.lb-title');
      var lbDate = lb.querySelector('.lb-date');
      var lbDl = lb.querySelector('.lb-download');
      var searchInput = document.getElementById('search');
      var cards = Array.from(document.querySelectorAll('.card'));
      var visibleCards = cards.slice();
      var currentIdx = -1;
      var activeFilters = {};
      var searchIndex = null;
      var debounceTimer = null;
      var selectedColorHex = null;
      var COLOR_THRESHOLD = 0.35;

      var subjects = ['landscape','mountain','ocean','lake','river','forest',
        'desert','cave','island','city','architecture','bridge','castle',
        'ruins','animal','bird','flower','garden','farm','snow','ice','aurora'];

      var filtersEl = document.getElementById('filters');
      var colorLabel = document.createElement('label');
      colorLabel.htmlFor = 'color-filter';
      colorLabel.className = 'filter-label';
      colorLabel.textContent = 'Color';
      var colorInput = document.createElement('input');
      colorInput.type = 'color';
      colorInput.id = 'color-filter';
      colorInput.setAttribute('aria-label', 'Filter by color');
      colorInput.style.cssText = 'width:28px;height:28px;padding:2px;cursor:pointer;border-radius:6px;border:1px solid #333;background:var(--card);';
      filtersEl.appendChild(colorLabel);
      filtersEl.appendChild(colorInput);
      colorInput.addEventListener('change', function() {
        selectedColorHex = colorInput.value || null;
        clearBtn.classList.toggle('show', Object.keys(activeFilters).length > 0 || selectedColorHex != null);
        applyFilters();
      });
      subjects.forEach(function(s) {
        var btn = document.createElement('button');
        btn.className = 'filter-pill';
        btn.textContent = s;
        btn.setAttribute('data-subject', s);
        btn.addEventListener('click', function() {
          if (activeFilters[s]) { delete activeFilters[s]; btn.classList.remove('active'); }
          else { activeFilters[s] = true; btn.classList.add('active'); }
          clearBtn.classList.toggle('show', Object.keys(activeFilters).length > 0 || selectedColorHex != null);
          applyFilters();
        });
        filtersEl.appendChild(btn);
      });
      var clearBtn = document.createElement('button');
      clearBtn.className = 'filter-clear';
      clearBtn.textContent = 'Clear filters';
      filtersEl.appendChild(clearBtn);
      clearBtn.addEventListener('click', function() {
        activeFilters = {};
        selectedColorHex = null;
        colorInput.value = '#000000';
        filtersEl.querySelectorAll('.filter-pill').forEach(function(b) { b.classList.remove('active'); });
        clearBtn.classList.remove('show');
        applyFilters();
      });

      fetch('search.json')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          searchIndex = new Map();
          data.forEach(function(rec) { searchIndex.set(rec.s, rec); });
          searchInput.disabled = false;
          searchInput.placeholder = 'Search images\\u2026';
        })
        .catch(function() {
          console.warn('Failed to load search.json, falling back to title search');
          searchInput.disabled = false;
          searchInput.placeholder = 'Search by title\\u2026';
        });

      function getRec(card) {
        if (!searchIndex) return null;
        return searchIndex.get(card.querySelector('a').getAttribute('data-slug')) || null;
      }

      function hexToRgbNorm(hex) {
        var m = (hex || '').match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
        if (!m) return null;
        return [
          parseInt(m[1], 16) / 255,
          parseInt(m[2], 16) / 255,
          parseInt(m[3], 16) / 255
        ];
      }
      function hexDistance(hex1, hex2) {
        var a = hexToRgbNorm(hex1);
        var b = hexToRgbNorm(hex2);
        if (!a || !b) return 2;
        var sum = 0;
        for (var i = 0; i < 3; i++) { var d = a[i] - b[i]; sum += d * d; }
        return Math.sqrt(sum);
      }

      function getQueryVariants(word) {
        var variants = [word];
        if (word.length > 4 && word.slice(-2) === 'es') variants.push(word.slice(0, -2));
        else if (word.length > 3 && word.slice(-1) === 's' && word.slice(-2) !== 'ss' && word.slice(-2) !== 'us') variants.push(word.slice(0, -1));
        if (word.slice(-1) !== 's') variants.push(word + 's');
        var seen = {};
        return variants.filter(function(v) { if (seen[v]) return false; seen[v] = true; return true; });
      }

      function applyFilters() {
        var q = (searchInput.value || '').trim().toLowerCase();
        var activeKeys = Object.keys(activeFilters);
        var terms = q ? q.split(/\\s+/) : [];
        var regexes = terms.map(function(t) {
          var variants = getQueryVariants(t);
          var escaped = variants.map(function(v) { return v.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&'); });
          return new RegExp('\\\\b(' + escaped.join('|') + ')\\\\b', 'i');
        });
        visibleCards = [];
        cards.forEach(function(card) {
          var a = card.querySelector('a');
          var rec = getRec(card);
          var textMatch = true;
          if (regexes.length > 0) {
            var s = rec ? rec.q : (a.getAttribute('data-title') || '') + ' ' + (a.getAttribute('data-date') || '');
            textMatch = regexes.every(function(rx) { return rx.test(s); });
          }
          var tagMatch = true;
          if (activeKeys.length > 0) {
            var subs = rec ? (rec.sub || '').split(',') : [];
            tagMatch = activeKeys.some(function(k) { return subs.indexOf(k) >= 0; });
          }
          var colorMatch = true;
          if (selectedColorHex != null && selectedColorHex !== '') {
            var cp = rec && rec.cp ? rec.cp : [];
            colorMatch = false;
            for (var i = 0; i < cp.length; i++) {
              var palHex = cp[i] && cp[i].hex;
              if (palHex && hexDistance(selectedColorHex, palHex) <= COLOR_THRESHOLD) {
                colorMatch = true;
                break;
              }
            }
          }
          var show = textMatch && tagMatch && colorMatch;
          card.style.display = show ? '' : 'none';
          if (show) visibleCards.push(card);
        });
      }

      function openLightbox(idx) {
        var card = visibleCards[idx];
        if (!card) return;
        var a = card.querySelector('a');
        lbImg.src = a.getAttribute('href');
        lbTitle.textContent = a.getAttribute('data-title') || '';
        lbDate.textContent = a.getAttribute('data-date') || '';
        lbDl.href = a.getAttribute('href');
        currentIdx = idx;
        lb.classList.add('show');
        document.body.style.overflow = 'hidden';
      }

      function closeLightbox() {
        lb.classList.remove('show');
        lbImg.src = '';
        document.body.style.overflow = '';
        currentIdx = -1;
      }

      function navigate(delta) {
        if (currentIdx < 0 || visibleCards.length === 0) return;
        var next = (currentIdx + delta + visibleCards.length) % visibleCards.length;
        openLightbox(next);
      }

      cards.forEach(function(card) {
        card.querySelector('a').addEventListener('click', function(e) {
          e.preventDefault();
          var idx = visibleCards.indexOf(card);
          if (idx >= 0) openLightbox(idx);
        });
      });

      lb.querySelector('.lb-close').addEventListener('click', closeLightbox);
      document.getElementById('lb-prev').addEventListener('click', function(e) { e.stopPropagation(); navigate(-1); });
      document.getElementById('lb-next').addEventListener('click', function(e) { e.stopPropagation(); navigate(1); });
      lb.addEventListener('click', function(e) { if (e.target === lb) closeLightbox(); });

      document.addEventListener('keydown', function(e) {
        if (!lb.classList.contains('show')) return;
        if (e.key === 'Escape') closeLightbox();
        else if (e.key === 'ArrowLeft') navigate(-1);
        else if (e.key === 'ArrowRight') navigate(1);
      });

      searchInput.addEventListener('input', function() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(applyFilters, 200);
      });
    })();
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
            tags = entry.get("tags", {})
            subjects = tags.get("subject", [])
            tag_pills = "".join(
                f'<span class="card-tag">{html.escape(s)}</span>' for s in subjects
            )
            f.write(
                f'    <div class="card"><a href="{bing_url}" '
                f'data-slug="{slug}" data-title="{title}" data-date="{date_str}">'
                f'<img src="{thumb}" alt="{title}" loading="lazy" '
                f'onerror="this.closest(\'.card\').style.display=\'none\'">'
                f'<span class="card-title">{title}</span>'
                f'<span class="card-date">{date_str}</span>'
                f'<div class="card-tags">{tag_pills}</div>'
                f"</a></div>\n"
            )
        f.write(INDEX_TAIL)
    print(f"Wrote index.html ({len(sorted_slugs)} cards)")


def build_search_index(entries):
    """Build search.json with pre-concatenated search strings."""
    sorted_slugs = sorted(
        entries.keys(), key=lambda k: (entries[k]["date"], k), reverse=True
    )
    index = []
    for slug in sorted_slugs:
        entry = entries[slug]
        tags = entry.get("tags", {})
        parts = [
            entry.get("title") or slug,
            " ".join(tags.get("subject", [])),
            tags.get("country") or "",
            tags.get("mood") or "",
            tags.get("season") or "",
            tags.get("region") or "",
            tags.get("time_of_day") or "",
        ]
        if tags.get("keywords"):
            parts.append(" ".join(tags["keywords"]))
        if tags.get("search_text"):
            parts.append(tags["search_text"])
        if not tags.get("search_text") and tags.get("ai_description"):
            parts.append(tags["ai_description"])
        palette = tags.get("color_palette") or []
        if palette:
            parts.append(" ".join(c.get("name") or "" for c in palette if isinstance(c, dict)))
        q = " ".join(p for p in parts if p).lower()
        index.append({
            "s": slug,
            "q": q,
            "ai": tags.get("ai_description") or "",
            "co": tags.get("country") or "",
            "sub": ",".join(tags.get("subject", [])),
            "sea": tags.get("season") or "",
            "mood": tags.get("mood") or "",
            "cp": tags.get("color_palette", []),
        })
    path = os.path.join(DEPLOY_DIR, "search.json")
    with open(path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    size_kb = os.path.getsize(path) / 1024
    print(f"Wrote search.json ({len(index)} entries, {size_kb:.0f} KB)")


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
    purge_invalid(entries)
    try:
        merge_bing_api(entries)
    except Exception as exc:
        print(f"Warning: Bing API fetch failed ({exc}), continuing with existing data")
    dedup(entries)
    print(f"Total gallery entries: {len(entries)}")

    save_metadata(entries)
    build_index(entries)
    build_search_index(entries)
    commit_and_push(entries)


if __name__ == "__main__":
    main()
