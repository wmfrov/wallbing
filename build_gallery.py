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
    .search-wrap { margin-top: 1rem; display: flex; align-items: center; gap: 1.25rem; flex-wrap: wrap; }
    .search-wrap input { width: 100%; max-width: 380px; padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #333; background: var(--card); color: var(--text); font-family: inherit; font-size: 0.9rem; outline: none; transition: border-color 0.2s; }
    .search-wrap input::placeholder { color: var(--muted); }
    .search-wrap input:focus { border-color: #555; }
    .stats-bar { color: var(--muted); font-size: 0.8rem; font-weight: 300; line-height: 1.4; }
    .filters { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 1.25rem; display: flex; flex-direction: column; gap: 0.4rem; }
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
    .card-colors { display: flex; height: 5px; }
    .card-color { flex: 1; }
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
    <h1>Bing image of the day</h1>
    <p class="meta">New photo each day from Bing. Click any image to view full size.</p>
    <div class="search-wrap">
      <input type="text" id="search" placeholder="Loading search\u2026" autocomplete="off" disabled>
      <span class="stats-bar" id="stats-bar"></span>
    </div>
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
      var statsEl = document.getElementById('stats-bar');
      var cards = Array.from(document.querySelectorAll('.card'));
      var visibleCards = cards.slice();
      var currentIdx = -1;
      var searchIndex = null;
      var browseIndex = null;
      var debounceTimer = null;

      // Multi-dimensional filter state: AND across dimensions, OR within
      var activeFilters = { subject:{}, mood:{}, season:{}, tod:{}, country:{}, color:{} };

      // Color family definitions (names drawn from color_extract.py CSS_COLORS vocab)
      var colorFamilies = [
        {id:'red',    label:'Red',       hex:'#c94040',
         names:['red','dark red','crimson','firebrick','tomato','coral','indian red',
                'light coral','dark salmon','salmon','light salmon','orange red','maroon']},
        {id:'orange', label:'Orange',    hex:'#d97020',
         names:['dark orange','orange']},
        {id:'yellow', label:'Yellow',    hex:'#c0980a',
         names:['gold','golden rod','pale golden rod','yellow','dark golden rod',
                'dark khaki','khaki','olive']},
        {id:'green',  label:'Green',     hex:'#3d8c3d',
         names:['dark olive green','olive drab','dark green','green','forest green',
                'lime green','light green','pale green','dark sea green',
                'medium spring green','spring green','sea green','medium aqua marine',
                'medium sea green','light sea green','lawn green','chartreuse',
                'green yellow','lime','yellow green']},
        {id:'teal',   label:'Teal',      hex:'#1f8a7d',
         names:['teal','dark cyan','dark turquoise','turquoise','medium turquoise',
                'pale turquoise','aqua marine','cyan','light cyan']},
        {id:'blue',   label:'Blue',      hex:'#2e6fad',
         names:['powder blue','cadet blue','steel blue','corn flower blue','deep sky blue',
                'dodger blue','light blue','sky blue','light sky blue','midnight blue',
                'navy','dark blue','medium blue','blue','royal blue','light steel blue']},
        {id:'purple', label:'Purple',    hex:'#7c3fbf',
         names:['blue violet','indigo','dark slate blue','slate blue','medium slate blue',
                'medium purple','dark magenta','dark violet','dark orchid','medium orchid',
                'purple','thistle','plum','violet','magenta','orchid',
                'medium violet red','pale violet red','deep pink','hot pink',
                'light pink','pink']},
        {id:'brown',  label:'Brown',     hex:'#7a4e28',
         names:['saddle brown','sienna','chocolate','peru','sandy brown','burly wood',
                'tan','rosy brown','brown']},
        {id:'gray',   label:'Gray',      hex:'#666',
         names:['dark slate gray','slate gray','light slate gray','dim gray','gray',
                'dark gray','silver','light gray','gainsboro','white smoke']},
        {id:'white',  label:'White',     hex:'#ccc',
         names:['white','snow','ivory','azure','honeydew','ghost white','floral white',
                'alice blue','mint cream','linen','old lace','antique white','beige',
                'blanched almond','misty rose','lavender blush']}
      ];

      var colorNameToFamily = {};
      colorFamilies.forEach(function(fam) {
        fam.names.forEach(function(n) { colorNameToFamily[n] = fam.id; });
      });

      var subjectOrder = ['landscape','mountain','ocean','lake','river','forest',
        'desert','cave','island','city','architecture','bridge','castle','ruins',
        'animal','bird','flower','garden','farm','snow','ice','aurora','two_animals'];
      var subjectLabels = {'two_animals':'Two animals'};
      var todOrder = ['dawn','day','dusk','night'];
      var seasonOrder = ['spring','summer','autumn','winter'];

      var filtersEl = document.getElementById('filters');
      var clearBtn = document.createElement('button');
      clearBtn.className = 'filter-clear';
      clearBtn.textContent = 'Clear filters';
      filtersEl.appendChild(clearBtn);

      function updateClearBtn() {
        var any = Object.keys(activeFilters).some(function(c) {
          return Object.keys(activeFilters[c]).length > 0;
        });
        clearBtn.classList.toggle('show', any);
      }

      clearBtn.addEventListener('click', function() {
        Object.keys(activeFilters).forEach(function(c) { activeFilters[c] = {}; });
        filtersEl.querySelectorAll('.filter-pill').forEach(function(b) { b.classList.remove('active'); });
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

      function buildColorGroup() {
        var group = document.createElement('div');
        group.className = 'filter-group';
        var lbl = document.createElement('span');
        lbl.className = 'filter-label';
        lbl.textContent = 'Color';
        group.appendChild(lbl);
        colorFamilies.forEach(function(fam) {
          var btn = document.createElement('button');
          btn.className = 'filter-pill';
          btn.setAttribute('data-category', 'color');
          btn.setAttribute('data-value', fam.id);
          if (activeFilters.color[fam.id]) btn.classList.add('active');
          var sw = document.createElement('span');
          sw.className = 'pill-swatch';
          sw.style.background = fam.hex;
          btn.appendChild(sw);
          btn.appendChild(document.createTextNode(fam.label));
          btn.addEventListener('click', function() {
            if (activeFilters.color[fam.id]) { delete activeFilters.color[fam.id]; btn.classList.remove('active'); }
            else { activeFilters.color[fam.id] = true; btn.classList.add('active'); }
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
          var topSea = Object.keys(b.season_counts).sort(function(a,b) {
            return b.season_counts[b] - b.season_counts[a];
          });
          // sort properly
          var seaEntries = Object.keys(b.season_counts).map(function(k) { return [k, b.season_counts[k]]; });
          seaEntries.sort(function(a,b) { return b[1]-a[1]; });
          if (seaEntries[0]) parts.push('mostly ' + seaEntries[0][0]);
        }
        if (b.mood_counts) {
          var moodEntries = Object.keys(b.mood_counts).map(function(k) { return [k, b.mood_counts[k]]; });
          moodEntries.sort(function(a,b) { return b[1]-a[1]; });
          var topMoods = moodEntries.slice(0,2).map(function(e) { return e[0]; });
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

        if (b.country_counts) {
          var coItems = Object.keys(b.country_counts).map(function(k) { return [k, b.country_counts[k]]; });
          coItems.sort(function(a,b) { return b[1]-a[1]; });
          buildFilterGroup('Country', coItems.map(function(e) {
            return {value:e[0], label:e[0]+' ('+e[1]+')'};
          }), 'country', activeFilters.country);
        }

        buildColorGroup();
      }

      function initFromUrl() {
        var params = new URLSearchParams(location.search);
        var dims = ['subject','mood','season','tod','country','color'];
        dims.forEach(function(dim) {
          var val = params.get(dim);
          if (val && activeFilters[dim] !== undefined) {
            activeFilters[dim][val] = true;
            var btn = filtersEl.querySelector('[data-category="'+dim+'"][data-value="'+val+'"]');
            if (btn) btn.classList.add('active');
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

        // Build a slug Set for each active non-color dimension
        var slugSets = {};
        var dimIndex = {
          subject: browseIndex && browseIndex.subject,
          mood:    browseIndex && browseIndex.mood,
          season:  browseIndex && browseIndex.season,
          tod:     browseIndex && browseIndex.tod,
          country: browseIndex && browseIndex.country
        };
        Object.keys(dimIndex).forEach(function(dim) {
          var keys = Object.keys(activeFilters[dim]);
          var idx = dimIndex[dim];
          if (!keys.length || !idx) return;
          var set = new Set();
          keys.forEach(function(k) { var arr = idx[k]; if (arr) arr.forEach(function(s) { set.add(s); }); });
          slugSets[dim] = set;
        });

        var activeColorFams = Object.keys(activeFilters.color);

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

          // AND across dimensions, OR within each dimension
          var dimMatch = Object.keys(slugSets).every(function(dim) {
            return slugSets[dim].has(slug);
          });

          var colorMatch = true;
          if (activeColorFams.length > 0) {
            var palette = rec && rec.cp ? rec.cp : [];
            var cardFams = {};
            palette.forEach(function(c) {
              var f = colorNameToFamily[c.name];
              if (f) cardFams[f] = true;
            });
            colorMatch = activeColorFams.some(function(f) { return cardFams[f]; });
          }

          var show = textMatch && dimMatch && colorMatch;
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
            colors = tags.get("color_palette") or []
            color_strip = ""
            if colors:
                swatches = "".join(
                    f'<span class="card-color" style="background:{c["hex"]}"'
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
        tod = tags.get("time_of_day")
        if tod and tod != "null":
            by_tod[tod].append(slug)

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
    if by_tod:
        browse["tod"] = dict(by_tod)
        browse["tod_counts"] = {k: len(v) for k, v in by_tod.items()}
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
