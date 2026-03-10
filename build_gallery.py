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
    .search-wrap { margin-top: 1rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
    .search-wrap input { width: 100%; max-width: 380px; padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #333; background: var(--card); color: var(--text); font-family: inherit; font-size: 0.9rem; outline: none; transition: border-color 0.2s; }
    .search-wrap input::placeholder { color: var(--muted); }
    .search-wrap input:focus { border-color: #555; }
    .filter-toggle { padding: 0.55rem 0.9rem; border-radius: 8px; border: 1px solid #333; background: var(--card); color: var(--muted); font-family: inherit; font-size: 0.85rem; font-weight: 500; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; gap: 0.45rem; white-space: nowrap; }
    .filter-toggle:hover { border-color: #555; color: var(--text); }
    .filter-toggle.has-active { border-color: #666; color: var(--text); }
    .filter-count { font-size: 0.7rem; background: rgba(255,255,255,0.18); border-radius: 10px; padding: 0.05rem 0.4rem; display: none; }
    .filter-toggle.has-active .filter-count { display: inline; }
    .toggle-arrow { display: inline-block; transition: transform 0.2s; font-style: normal; line-height: 1; }
    .filter-toggle.open .toggle-arrow { transform: rotate(180deg); }
    .stats-bar { color: var(--muted); font-size: 0.8rem; font-weight: 300; line-height: 1.4; }
    .filters { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem; display: flex; flex-direction: column; gap: 0.4rem; overflow: hidden; max-height: 0; transition: max-height 0.3s ease, padding-bottom 0.3s ease; }
    .filters.open { max-height: 2000px; padding-bottom: 1.25rem; overflow: visible; }
    .filter-group { display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }
    .filter-label { font-size: 0.68rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: 0.06em; min-width: 7rem; flex-shrink: 0; }
    .filter-pill { padding: 0.3rem 0.7rem; border-radius: 20px; border: 1px solid #333; background: transparent; color: var(--muted); font-family: inherit; font-size: 0.75rem; font-weight: 500; cursor: pointer; transition: all 0.2s; text-transform: capitalize; display: inline-flex; align-items: center; gap: 0.3rem; }
    .filter-pill:hover { border-color: #555; color: var(--text); }
    .filter-pill.active { background: rgba(255,255,255,0.12); border-color: #666; color: var(--text); }
    .pill-swatch { width: 0.6rem; height: 0.6rem; border-radius: 50%; flex-shrink: 0; }
    .filter-clear { align-self: flex-start; margin-top: 0.1rem; padding: 0.3rem 0.7rem; border-radius: 20px; border: 1px solid transparent; background: none; color: var(--muted); font-family: inherit; font-size: 0.75rem; cursor: pointer; opacity: 0; pointer-events: none; transition: opacity 0.2s; }
    .filter-clear.show { opacity: 1; pointer-events: auto; }
    .filter-clear:hover { color: var(--text); }
    .grid { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 2rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { background: var(--card); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.35); transition: transform 0.2s ease, box-shadow 0.2s ease; }
    .card:hover { transform: translateY(-4px); box-shadow: 0 12px 40px rgba(0,0,0,0.45); }
    .card a { display: block; text-decoration: none; color: inherit; }
    .card img { width: 100%; height: 200px; object-fit: cover; display: block; }
    .card-colors { display: flex; height: 5px; transform-origin: top; transition: transform 0.25s ease; }
    .card:hover .card-colors { transform: scaleY(4.4); }
    .card-color { transition: flex 0.25s; }
    .card-title { display: block; padding: 0.75rem 1rem 0.15rem; font-size: 0.85rem; font-weight: 500; color: var(--muted); }
    .card-date { display: block; padding: 0 1rem 0.75rem; font-size: 0.75rem; font-weight: 300; color: var(--muted); opacity: 0.9; }
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
    .lb-palette { display: flex; gap: 6px; margin-top: 0.75rem; justify-content: center; }
    .lb-palette-swatch { width: 36px; height: 36px; border-radius: 6px; cursor: pointer; border: 2px solid transparent; transition: border-color 0.15s, transform 0.15s; flex-shrink: 0; }
    .lb-palette-swatch:hover { transform: scale(1.1); border-color: rgba(255,255,255,0.5); }
    .similarity-banner { display: none; max-width: 1400px; margin: 0 auto; padding: 0.5rem 1.5rem; font-size: 0.8rem; color: var(--muted); align-items: center; gap: 0.75rem; }
    .similarity-banner.show { display: flex; }
    .similarity-banner-swatch { width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }
    .similarity-clear { background: none; border: 1px solid #444; border-radius: 12px; color: var(--muted); font-family: inherit; font-size: 0.75rem; padding: 0.2rem 0.6rem; cursor: pointer; }
    .similarity-clear:hover { color: var(--text); }
    .color-grid-wrap { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 0.75rem; }
    .color-grid { display: flex; flex-wrap: wrap; gap: 3px; align-items: center; }
    .color-cell { flex: 1; min-width: 44px; height: 28px; border: none; border-radius: 3px; cursor: pointer; padding: 0; transition: transform 0.15s, opacity 0.15s; opacity: 0.75; }
    .color-cell:hover { transform: scaleY(1.43); opacity: 1; }
    .color-cell.active { transform: scaleY(1.43); opacity: 1; outline: 2px solid rgba(255,255,255,0.6); outline-offset: 1px; }
    .geo-dropdown-wrap { position: relative; display: inline-block; }
    .geo-trigger { padding: 0.3rem 0.7rem; border-radius: 20px; border: 1px solid #333; background: transparent; color: var(--muted); font-family: inherit; font-size: 0.75rem; font-weight: 500; cursor: pointer; transition: all 0.2s; display: inline-flex; align-items: center; gap: 0.3rem; }
    .geo-trigger:hover { border-color: #555; color: var(--text); }
    .geo-trigger.active { background: rgba(255,255,255,0.12); border-color: #666; color: var(--text); }
    .geo-dropdown { display: none; position: absolute; top: calc(100% + 4px); left: 0; background: var(--card); border: 1px solid #333; border-radius: 8px; max-height: 360px; overflow-y: auto; width: 280px; z-index: 50; box-shadow: 0 8px 32px rgba(0,0,0,0.5); }
    .geo-dropdown.open { display: block; }
    .geo-search { width: calc(100% - 1rem); margin: 0.5rem; padding: 0.4rem 0.6rem; border-radius: 6px; border: 1px solid #333; background: var(--bg); color: var(--text); font-family: inherit; font-size: 0.8rem; outline: none; }
    .geo-search:focus { border-color: #555; }
    .geo-region-header { position: sticky; top: 0; padding: 0.35rem 0.75rem; font-size: 0.65rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: 0.06em; background: var(--card); }
    .geo-option { padding: 0.3rem 0.75rem; font-size: 0.8rem; color: var(--muted); cursor: pointer; transition: all 0.15s; display: flex; justify-content: space-between; }
    .geo-option:hover { background: rgba(255,255,255,0.06); color: var(--text); }
    .geo-option.active { background: rgba(255,255,255,0.1); color: var(--text); }
    .geo-count { font-size: 0.7rem; color: #555; }
  </style>
</head>
<body>
  <header class="header">
    <h1>Bing image of the day</h1>
    <p class="meta">New photo each day from Bing. Click any image to view full size.</p>
    <div class="search-wrap">
      <input type="text" id="search" placeholder="Loading search\u2026" autocomplete="off" disabled>
      <button class="filter-toggle" id="filter-toggle" aria-expanded="false">
        Filters <span class="filter-count" id="filter-count"></span><i class="toggle-arrow">&#8964;</i>
      </button>
      <span class="stats-bar" id="stats-bar"></span>
    </div>
  </header>
  <div class="filters" id="filters"></div>
  <div class="similarity-banner" id="similarity-banner">
    <span class="similarity-banner-swatch" id="similarity-swatch"></span>
    <span id="similarity-label">Showing images with similar colors</span>
    <button class="similarity-clear" id="similarity-clear">Clear</button>
  </div>
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
      <div class="lb-palette" id="lb-palette"></div>
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
      var statsEl = document.getElementById('stats-bar');
      var cards = Array.from(document.querySelectorAll('.card'));
      var visibleCards = cards.slice();
      var currentIdx = -1;
      var searchIndex = null;
      var browseIndex = null;
      var debounceTimer = null;

      // Multi-dimensional filter state: AND across dimensions, AND within
      var activeFilters = { subject:{}, mood:{}, season:{}, tod:{}, country:{}, color_bucket:{} };

      var subjectOrder = ['landscape','mountain','ocean','lake','river','forest',
        'desert','cave','island','city','architecture','bridge','castle','ruins',
        'animal','bird','flower','garden','farm','snow','ice','aurora','two_animals'];
      var subjectLabels = {'two_animals':'Two animals'};
      var todOrder = ['dawn','day','dusk','night'];
      var seasonOrder = ['spring','summer','autumn','winter'];

      var filtersEl = document.getElementById('filters');
      var filterToggle = document.getElementById('filter-toggle');
      var filterCountEl = document.getElementById('filter-count');
      var clearBtn = document.createElement('button');
      clearBtn.className = 'filter-clear';
      clearBtn.textContent = 'Clear filters';
      filtersEl.appendChild(clearBtn);

      filterToggle.addEventListener('click', function() {
        var open = filtersEl.classList.toggle('open');
        filterToggle.classList.toggle('open', open);
        filterToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });

      function updateClearBtn() {
        var total = Object.keys(activeFilters).reduce(function(sum, c) {
          return sum + Object.keys(activeFilters[c]).length;
        }, 0);
        clearBtn.classList.toggle('show', total > 0);
        filterToggle.classList.toggle('has-active', total > 0);
        if (filterCountEl) filterCountEl.textContent = total > 0 ? total : '';
      }

      clearBtn.addEventListener('click', function() {
        Object.keys(activeFilters).forEach(function(c) { activeFilters[c] = {}; });
        filtersEl.querySelectorAll('.filter-pill').forEach(function(b) { b.classList.remove('active'); });
        document.querySelectorAll('.color-cell').forEach(function(b) { b.classList.remove('active'); });
        document.querySelectorAll('.geo-option').forEach(function(b) { b.classList.remove('active'); });
        var geoTrigger = document.querySelector('.geo-trigger');
        if (geoTrigger) { geoTrigger.textContent = 'Location \u25BE'; geoTrigger.classList.remove('active'); }
        updateClearBtn();
        applyFilters();
      });

      function buildFilterGroup(label, items, category, stateObj) {
        if (!items || !items.length) return;
        var group = document.createElement('div');
        group.className = 'filter-group';
        var lbl = document.createElement('span');
        lbl.className = 'filter-label';
        lbl.textContent = label;
        group.appendChild(lbl);
        items.forEach(function(item) {
          var btn = document.createElement('button');
          btn.className = 'filter-pill';
          btn.textContent = item.label;
          btn.setAttribute('data-category', category);
          btn.setAttribute('data-value', item.value);
          if (stateObj[item.value]) btn.classList.add('active');
          btn.addEventListener('click', function() {
            if (stateObj[item.value]) { delete stateObj[item.value]; btn.classList.remove('active'); }
            else { stateObj[item.value] = true; btn.classList.add('active'); }
            updateClearBtn();
            applyFilters();
          });
          group.appendChild(btn);
        });
        filtersEl.insertBefore(group, clearBtn);
      }

      function buildStats(b) {
        if (!statsEl || !b) return;
        var parts = [cards.length + ' photos'];
        if (b.country_counts) {
          parts.push(Object.keys(b.country_counts).length + ' countries');
        }
        if (b.season_counts) {
          var seaEntries = Object.keys(b.season_counts).map(function(k) { return [k, b.season_counts[k]]; });
          seaEntries.sort(function(x, y) { return y[1] - x[1]; });
          if (seaEntries[0]) parts.push('mostly ' + seaEntries[0][0]);
        }
        if (b.mood_counts) {
          var moodEntries = Object.keys(b.mood_counts).map(function(k) { return [k, b.mood_counts[k]]; });
          moodEntries.sort(function(x, y) { return y[1] - x[1]; });
          var topMoods = moodEntries.slice(0, 2).map(function(e) { return e[0]; });
          if (topMoods.length) parts.push(topMoods.join(', '));
        }
        statsEl.textContent = parts.join(' \u00b7 ');
      }

      function buildAllFilters(b) {
        var sc = b.subject_counts || {};
        var subjItems = subjectOrder.filter(function(s) { return sc[s]; }).map(function(s) {
          return {value:s, label:(subjectLabels[s]||s)+' ('+sc[s]+')'};
        });
        buildFilterGroup('Subject', subjItems, 'subject', activeFilters.subject);

        if (b.mood_counts) {
          var moodItems = Object.keys(b.mood_counts).map(function(k) { return [k, b.mood_counts[k]]; });
          moodItems.sort(function(a,b) { return b[1]-a[1]; });
          buildFilterGroup('Mood', moodItems.map(function(e) {
            return {value:e[0], label:e[0]+' ('+e[1]+')'};
          }), 'mood', activeFilters.mood);
        }

        if (b.season_counts) {
          var seaItems = seasonOrder.filter(function(s) { return b.season_counts[s]; }).map(function(s) {
            return {value:s, label:s+' ('+b.season_counts[s]+')'};
          });
          buildFilterGroup('Season', seaItems, 'season', activeFilters.season);
        }

        if (b.tod_counts) {
          var todItems = todOrder.filter(function(s) { return b.tod_counts[s]; }).map(function(s) {
            return {value:s, label:s+' ('+b.tod_counts[s]+')'};
          });
          buildFilterGroup('Time of day', todItems, 'tod', activeFilters.tod);
        }

        buildGeoDropdown(b);
      }

      function initFromUrl() {
        var params = new URLSearchParams(location.search);
        var dims = ['subject','mood','season','tod','country','color_bucket'];
        dims.forEach(function(dim) {
          var val = params.get(dim);
          if (val && activeFilters[dim] !== undefined) {
            activeFilters[dim][val] = true;
            if (dim === 'color_bucket') {
              var cell = document.querySelector('.color-cell[data-color-bucket="'+val+'"]');
              if (cell) cell.classList.add('active');
            } else if (dim === 'country') {
              var opt = document.querySelector('.geo-option[data-country="'+val+'"]');
              if (opt) opt.classList.add('active');
              var geoTrigger = document.querySelector('.geo-trigger');
              if (geoTrigger) {
                var cnt = Object.keys(activeFilters.country).length;
                geoTrigger.textContent = cnt ? 'Location ('+cnt+') \u25BE' : 'Location \u25BE';
                geoTrigger.classList.toggle('active', cnt > 0);
              }
            } else {
              var btn = filtersEl.querySelector('[data-category="'+dim+'"][data-value="'+val+'"]');
              if (btn) btn.classList.add('active');
            }
          }
        });
        updateClearBtn();
        applyFilters();
      }

      Promise.all([
        fetch('search.json').then(function(r) { return r.json(); }),
        fetch('browse.json').then(function(r) { return r.json(); })
      ]).then(function(results) {
        searchIndex = new Map();
        results[0].forEach(function(rec) { searchIndex.set(rec.s, rec); });
        browseIndex = results[1];
        searchInput.disabled = false;
        searchInput.placeholder = 'Refine by keyword\\u2026';
        buildStats(browseIndex);
        buildAllFilters(browseIndex);
        buildColorGrid(browseIndex);
        initFromUrl();
      }).catch(function() {
        searchInput.disabled = false;
        searchInput.placeholder = 'Search by title\\u2026';
        applyFilters();
      });

      function getRec(card) {
        if (!searchIndex) return null;
        return searchIndex.get(card.querySelector('a').getAttribute('data-slug')) || null;
      }

      function applyFilters() {
        var q = (searchInput.value || '').trim().toLowerCase();
        var terms = q ? q.split(/\\s+/) : [];
        var regexes = terms.map(function(t) {
          return new RegExp('\\\\b' + t.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '\\\\b', 'i');
        });

        // Build a slug Set for each active dimension (AND within, AND across)
        var slugSets = {};
        var dimIndex = {
          subject:    browseIndex && browseIndex.subject,
          mood:       browseIndex && browseIndex.mood,
          season:     browseIndex && browseIndex.season,
          tod:        browseIndex && browseIndex.tod,
          country:    browseIndex && browseIndex.country,
          color_bucket: browseIndex && browseIndex.color_bucket
        };
        Object.keys(dimIndex).forEach(function(dim) {
          var keys = Object.keys(activeFilters[dim]);
          var idx = dimIndex[dim];
          if (!keys.length || !idx) return;
          var set = null;
          keys.forEach(function(k) {
            var arr = idx[k];
            if (!arr) return;
            if (!set) { set = new Set(arr); }
            else { set = new Set(arr.filter(function(s) { return set.has(s); })); }
          });
          if (set) slugSets[dim] = set;
        });

        visibleCards = [];
        cards.forEach(function(card) {
          var a = card.querySelector('a');
          var slug = a.getAttribute('data-slug');
          var rec = getRec(card);

          var textMatch = true;
          if (regexes.length > 0) {
            var s = rec ? rec.q : (a.getAttribute('data-title') || '') + ' ' + (a.getAttribute('data-date') || '');
            textMatch = regexes.every(function(rx) { return rx.test(s); });
          }

          // AND across dimensions
          var dimMatch = Object.keys(slugSets).every(function(dim) {
            return slugSets[dim].has(slug);
          });

          var show = textMatch && dimMatch;
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
        var paletteEl = document.getElementById('lb-palette');
        paletteEl.innerHTML = '';
        var rec = getRec(card);
        if (rec && rec.cp) {
          rec.cp.forEach(function(c) {
            var sw = document.createElement('div');
            sw.className = 'lb-palette-swatch';
            sw.style.background = c.hex;
            sw.title = c.name + ' (' + Math.round(c.w*100) + '%)';
            sw.addEventListener('click', function(e) {
              e.stopPropagation();
              closeLightbox();
              showSimilar(c.hex, c.name);
            });
            paletteEl.appendChild(sw);
          });
        }
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
        if (currentIdx < 0 || !visibleCards.length) return;
        openLightbox((currentIdx + delta + visibleCards.length) % visibleCards.length);
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

      function buildColorGrid(browseData) {
        if (!browseData.color_bucket || !browseData.color_bucket_hex) return;
        var bucketToSlugs = browseData.color_bucket;
        var bucketToHex = browseData.color_bucket_hex;
        var bucketOrder = browseData.color_bucket_order || Object.keys(bucketToSlugs);
        var wrap = document.createElement('div');
        wrap.className = 'color-grid-wrap';
        var grid = document.createElement('div');
        grid.className = 'color-grid';
        bucketOrder.forEach(function(label) {
          if (!bucketToSlugs[label]) return;
          var hex = bucketToHex[label];
          var count = bucketToSlugs[label].length;
          var cell = document.createElement('button');
          cell.className = 'color-cell';
          cell.style.background = hex;
          cell.title = label + ' (' + count + ')';
          cell.setAttribute('data-color-bucket', label);
          if (activeFilters.color_bucket[label]) cell.classList.add('active');
          cell.addEventListener('click', function() {
            if (activeFilters.color_bucket[label]) { delete activeFilters.color_bucket[label]; cell.classList.remove('active'); }
            else { activeFilters.color_bucket[label] = true; cell.classList.add('active'); }
            updateClearBtn();
            applyFilters();
          });
          grid.appendChild(cell);
        });
        wrap.appendChild(grid);
        document.querySelector('.filters').before(wrap);
      }

      function buildGeoDropdown(b) {
        if (!b.country_counts) return;
        var countryToRegion = b.country_to_region || {};
        var countries = Object.keys(b.country_counts).map(function(k) {
          return { name: k, count: b.country_counts[k], region: countryToRegion[k] || 'Other' };
        });
        // Group by region
        var regionMap = {};
        countries.forEach(function(c) {
          if (!regionMap[c.region]) regionMap[c.region] = [];
          regionMap[c.region].push(c);
        });
        // Sort countries within each region by count desc
        Object.keys(regionMap).forEach(function(r) {
          regionMap[r].sort(function(a,b) { return b.count - a.count; });
        });
        // Sort regions by total count desc
        var regionOrder = Object.keys(regionMap).sort(function(a,b) {
          var ta = regionMap[a].reduce(function(s,c) { return s+c.count; }, 0);
          var tb = regionMap[b].reduce(function(s,c) { return s+c.count; }, 0);
          return tb - ta;
        });

        var group = document.createElement('div');
        group.className = 'filter-group';
        var lbl = document.createElement('span');
        lbl.className = 'filter-label';
        lbl.textContent = 'Location';
        group.appendChild(lbl);

        var ddWrap = document.createElement('div');
        ddWrap.className = 'geo-dropdown-wrap';
        var trigger = document.createElement('button');
        trigger.className = 'geo-trigger';
        trigger.textContent = 'Location \u25BE';
        ddWrap.appendChild(trigger);

        var dd = document.createElement('div');
        dd.className = 'geo-dropdown';
        var searchInput2 = document.createElement('input');
        searchInput2.className = 'geo-search';
        searchInput2.placeholder = 'Search countries\\u2026';
        dd.appendChild(searchInput2);

        var listEl = document.createElement('div');
        regionOrder.forEach(function(region) {
          var header = document.createElement('div');
          header.className = 'geo-region-header';
          header.textContent = region;
          header.setAttribute('data-region', region);
          listEl.appendChild(header);
          regionMap[region].forEach(function(c) {
            var opt = document.createElement('div');
            opt.className = 'geo-option';
            opt.setAttribute('data-country', c.name);
            opt.setAttribute('data-region', region);
            var nameSpan = document.createElement('span');
            nameSpan.textContent = c.name;
            var countSpan = document.createElement('span');
            countSpan.className = 'geo-count';
            countSpan.textContent = c.count;
            opt.appendChild(nameSpan);
            opt.appendChild(countSpan);
            if (activeFilters.country[c.name]) opt.classList.add('active');
            opt.addEventListener('click', function() {
              if (activeFilters.country[c.name]) { delete activeFilters.country[c.name]; opt.classList.remove('active'); }
              else { activeFilters.country[c.name] = true; opt.classList.add('active'); }
              var cnt = Object.keys(activeFilters.country).length;
              trigger.textContent = cnt ? 'Location ('+cnt+') \u25BE' : 'Location \u25BE';
              trigger.classList.toggle('active', cnt > 0);
              updateClearBtn();
              applyFilters();
            });
            listEl.appendChild(opt);
          });
        });
        dd.appendChild(listEl);
        ddWrap.appendChild(dd);
        group.appendChild(ddWrap);
        filtersEl.insertBefore(group, clearBtn);

        trigger.addEventListener('click', function(e) {
          e.stopPropagation();
          dd.classList.toggle('open');
        });
        document.addEventListener('click', function(e) {
          if (!ddWrap.contains(e.target)) dd.classList.remove('open');
        });

        searchInput2.addEventListener('input', function() {
          var q = searchInput2.value.toLowerCase();
          var visibleRegions = {};
          listEl.querySelectorAll('.geo-option').forEach(function(opt) {
            var name = opt.getAttribute('data-country').toLowerCase();
            var show = !q || name.indexOf(q) >= 0;
            opt.style.display = show ? '' : 'none';
            if (show) visibleRegions[opt.getAttribute('data-region')] = true;
          });
          listEl.querySelectorAll('.geo-region-header').forEach(function(h) {
            h.style.display = visibleRegions[h.getAttribute('data-region')] ? '' : 'none';
          });
        });
      }

      function hexToRgb(hex) {
        return [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
      }
      function rgbDist(a, b) {
        return Math.sqrt((a[0]-b[0])*(a[0]-b[0]) + (a[1]-b[1])*(a[1]-b[1]) + (a[2]-b[2])*(a[2]-b[2]));
      }
      var MAX_RGB_DIST = Math.sqrt(3 * 255 * 255);
      function similarityScore(queryHex, candidatePalette) {
        var qRgb = hexToRgb(queryHex);
        var score = 0;
        candidatePalette.forEach(function(c) {
          var d = rgbDist(qRgb, hexToRgb(c.hex));
          score += c.w * Math.max(0, 1 - d / MAX_RGB_DIST);
        });
        return score;
      }
      function showSimilar(queryHex, colorName) {
        if (!searchIndex) return;
        var scored = [];
        searchIndex.forEach(function(rec) {
          if (!rec.cp || !rec.cp.length) return;
          scored.push([rec.s, similarityScore(queryHex, rec.cp)]);
        });
        scored.sort(function(a,b) { return b[1]-a[1]; });
        var top = new Set(scored.slice(0, 60).map(function(x) { return x[0]; }));
        var slugToCard = {};
        cards.forEach(function(c) { slugToCard[c.querySelector('a').getAttribute('data-slug')] = c; });
        var grid = document.querySelector('.grid');
        scored.slice(0, 60).forEach(function(pair) {
          var card = slugToCard[pair[0]];
          if (card) { card.style.display = ''; grid.appendChild(card); }
        });
        cards.forEach(function(c) {
          if (!top.has(c.querySelector('a').getAttribute('data-slug'))) c.style.display = 'none';
        });
        visibleCards = scored.slice(0,60).map(function(p) { return slugToCard[p[0]]; }).filter(Boolean);
        var banner = document.getElementById('similarity-banner');
        document.getElementById('similarity-swatch').style.background = queryHex;
        document.getElementById('similarity-label').textContent =
          'Showing images similar in color to ' + colorName;
        banner.classList.add('show');
      }
      document.getElementById('similarity-clear').addEventListener('click', function() {
        document.getElementById('similarity-banner').classList.remove('show');
        applyFilters();
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
            colors = tags.get("color_palette") or []
            color_strip = ""
            if colors:
                swatches = "".join(
                    f'<span class="card-color" style="background:{c["hex"]};flex:{c["w"]}"'
                    f' title="{html.escape(c.get("name",""))}"></span>'
                    for c in colors[:5]
                )
                color_strip = f'<div class="card-colors">{swatches}</div>'
            f.write(
                f'    <div class="card"><a href="{bing_url}" '
                f'data-slug="{slug}" data-title="{title}" data-date="{date_str}">'
                f'<img src="{thumb}" alt="{title}" loading="lazy" '
                f'onerror="this.closest(\'.card\').style.display=\'none\'">'
                f'{color_strip}'
                f'<span class="card-title">{title}</span>'
                f'<span class="card-date">{date_str}</span>'
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
        ]
        if tags.get("keywords"):
            parts.append(" ".join(tags["keywords"]))
        if tags.get("search_text"):
            parts.append(tags["search_text"])
        if not tags.get("search_text") and tags.get("ai_description"):
            parts.append(tags["ai_description"])
        q = " ".join(p for p in parts if p).lower()
        index.append({
            "s": slug,
            "q": q,
            "ai": tags.get("ai_description") or "",
            "co": tags.get("country") or "",
            "sub": ",".join(tags.get("subject", [])),
            "sea": tags.get("season") or "",
            "mood": tags.get("mood") or "",
            "tod": tags.get("time_of_day") or "",
            "cp": tags.get("color_palette", []),
        })
    path = os.path.join(DEPLOY_DIR, "search.json")
    with open(path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    size_kb = os.path.getsize(path) / 1024
    print(f"Wrote search.json ({len(index)} entries, {size_kb:.0f} KB)")


COLOR_BUCKETS = [
    ("Red",     "#dc3545", ["red", "dark red", "crimson", "firebrick", "indian red", "maroon"]),
    ("Coral",   "#ff6b5b", ["tomato", "coral", "light coral", "salmon", "dark salmon", "light salmon", "orange red"]),
    ("Orange",  "#ff8c00", ["dark orange", "orange"]),
    ("Gold",    "#daa520", ["gold", "golden rod", "dark golden rod", "dark khaki"]),
    ("Yellow",  "#e6d520", ["yellow", "khaki", "pale golden rod", "olive", "lemon chiffon"]),
    ("Lime",    "#7cb342", ["yellow green", "lawn green", "chartreuse", "green yellow", "lime", "lime green", "olive drab"]),
    ("Green",   "#2e7d32", ["dark green", "green", "forest green", "dark olive green", "sea green", "medium sea green"]),
    ("Emerald", "#4caf82", ["medium spring green", "spring green", "light green", "pale green", "dark sea green", "medium aqua marine"]),
    ("Teal",    "#00897b", ["teal", "dark cyan", "light sea green"]),
    ("Cyan",    "#00bcd4", ["cyan", "dark turquoise", "turquoise", "medium turquoise", "pale turquoise", "aqua marine", "light cyan"]),
    ("Sky",     "#4db6e0", ["light blue", "sky blue", "light sky blue", "powder blue", "deep sky blue", "dodger blue", "cadet blue"]),
    ("Blue",    "#1e5fa8", ["steel blue", "corn flower blue", "royal blue", "blue", "medium blue", "dark blue", "navy", "midnight blue"]),
    ("Purple",  "#7b1fa2", ["blue violet", "indigo", "dark slate blue", "slate blue", "medium slate blue", "medium purple", "dark magenta", "dark violet", "dark orchid", "medium orchid", "purple"]),
    ("Pink",    "#e040a0", ["magenta", "orchid", "violet", "plum", "thistle", "medium violet red", "pale violet red", "deep pink", "hot pink", "light pink", "pink"]),
    ("Brown",   "#8d6e3e", ["saddle brown", "sienna", "chocolate", "peru", "sandy brown", "burly wood", "tan", "rosy brown", "brown"]),
    ("Gray",    "#9e9e9e", ["dark slate gray", "slate gray", "light slate gray", "dim gray", "gray", "dark gray", "silver", "light gray", "gainsboro", "white smoke", "white", "snow", "ivory", "azure", "honeydew", "ghost white", "floral white", "alice blue", "mint cream", "linen", "old lace", "antique white", "beige", "blanched almond", "misty rose", "lavender blush"]),
]

def build_browse_index(entries):
    """Build browse.json: category -> list of slugs (same order as gallery) and counts."""
    sorted_slugs = sorted(
        entries.keys(), key=lambda k: (entries[k]["date"], k), reverse=True
    )
    by_subject = defaultdict(list)
    by_season = defaultdict(list)
    by_mood = defaultdict(list)
    by_country = defaultdict(list)
    by_tod = defaultdict(list)
    country_to_region = {}

    # Build CSS name → bucket label mapping
    css_name_to_bucket = {}
    for label, _hex, css_names in COLOR_BUCKETS:
        for name in css_names:
            css_name_to_bucket[name] = label
    by_color_bucket = defaultdict(set)

    for slug in sorted_slugs:
        entry = entries[slug]
        tags = entry.get("tags", {})
        for s in tags.get("subject", []):
            by_subject[s].append(slug)
        sea = tags.get("season")
        if sea:
            by_season[sea].append(slug)
        mood = tags.get("mood")
        if mood:
            by_mood[mood].append(slug)
        co = tags.get("country")
        if co:
            by_country[co].append(slug)
            region = tags.get("region")
            if region and co not in country_to_region:
                country_to_region[co] = region
        tod = tags.get("time_of_day")
        if tod and tod != "null":
            by_tod[tod].append(slug)
        for c in tags.get("color_palette", []):
            cname = c.get("name")
            if cname:
                bucket = css_name_to_bucket.get(cname)
                if bucket:
                    by_color_bucket[bucket].add(slug)

    # Derive "two_animals" from existing tags: animal/bird + "two"/"pair" in keywords or search text
    two_animals_set = set(by_subject.get("two_animals", []))
    quantity_terms = ("two", "pair")
    for slug in sorted_slugs:
        if slug in two_animals_set:
            continue
        entry = entries[slug]
        tags = entry.get("tags", {})
        subs = tags.get("subject", [])
        if "animal" not in subs and "bird" not in subs:
            continue
        parts = [
            entry.get("title") or slug,
            " ".join(tags.get("subject", [])),
            tags.get("country") or "",
            tags.get("mood") or "",
            tags.get("season") or "",
        ]
        if tags.get("keywords"):
            parts.append(" ".join(tags["keywords"]))
        if tags.get("search_text"):
            parts.append(tags["search_text"])
        if not tags.get("search_text") and tags.get("ai_description"):
            parts.append(tags.get("ai_description") or "")
        searchable = " ".join(p for p in parts if p).lower()
        if any(re.search(r"\b" + re.escape(term) + r"\b", searchable) for term in quantity_terms):
            two_animals_set.add(slug)
    by_subject["two_animals"] = [s for s in sorted_slugs if s in two_animals_set]

    browse = {
        "subject": dict(by_subject),
        "subject_counts": {s: len(slugs) for s, slugs in by_subject.items()},
    }
    if by_season:
        browse["season"] = dict(by_season)
        browse["season_counts"] = {k: len(v) for k, v in by_season.items()}
    if by_mood:
        browse["mood"] = dict(by_mood)
        browse["mood_counts"] = {k: len(v) for k, v in by_mood.items()}
    if by_country:
        browse["country"] = dict(by_country)
        browse["country_counts"] = {k: len(v) for k, v in by_country.items()}
        browse["country_to_region"] = country_to_region
    if by_tod:
        browse["tod"] = dict(by_tod)
        browse["tod_counts"] = {k: len(v) for k, v in by_tod.items()}
    if by_color_bucket:
        # Preserve gallery order within each bucket
        slug_rank = {s: i for i, s in enumerate(sorted_slugs)}
        browse["color_bucket"] = {
            label: sorted(by_color_bucket[label], key=lambda s: slug_rank[s])
            for label, _hex, _names in COLOR_BUCKETS
            if label in by_color_bucket
        }
        browse["color_bucket_hex"] = {label: h for label, h, _names in COLOR_BUCKETS}
        browse["color_bucket_order"] = [label for label, _h, _n in COLOR_BUCKETS]
    path = os.path.join(DEPLOY_DIR, "browse.json")
    with open(path, "w") as f:
        json.dump(browse, f, separators=(",", ":"))
    size_kb = os.path.getsize(path) / 1024
    print(f"Wrote browse.json ({size_kb:.0f} KB)")


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
    build_browse_index(entries)
    commit_and_push(entries)


if __name__ == "__main__":
    main()
