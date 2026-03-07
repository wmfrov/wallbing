#!/usr/bin/env python3
"""
Read archive/archive.json (list of {url, date, title, key}) and write archive/index.html.
If env vars URL, DATE, TITLE, NAME are set, append one entry to archive.json first.
Run from repo root (gh-pages). Creates archive/ if needed.
"""
import json
import os
import sys

ARCHIVE_JSON = "archive/archive.json"
ARCHIVE_HTML = "archive/index.html"


def append_entry_from_env(root: str) -> None:
    url = os.environ.get("URL")
    if not url:
        return
    date_str = os.environ.get("DATE", "")
    title = os.environ.get("TITLE", "")
    name = os.environ.get("NAME", "")
    key = "images/" + name if name else ""
    json_path = os.path.join(root, ARCHIVE_JSON)
    entries = []
    if os.path.isfile(json_path):
        with open(json_path, "r") as f:
            entries = json.load(f)
    if not isinstance(entries, list):
        entries = []
    entries.append({"url": url, "date": date_str, "title": title, "key": key})
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(entries, f, indent=2)


HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bing wallpapers – full archive</title>
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
    .meta a { color: var(--accent); }
    .grid { max-width: 1400px; margin: 0 auto; padding: 0 1.5rem 2rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { background: var(--card); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,0.35); }
    .card a { display: block; padding: 0.75rem 1rem; text-decoration: none; color: inherit; font-size: 0.85rem; }
    .card a:hover { background: rgba(255,255,255,0.05); }
    .card-title { font-weight: 500; color: var(--text); }
    .card-date { font-size: 0.75rem; font-weight: 300; color: var(--muted); margin-top: 0.25rem; }
  </style>
</head>
<body>
  <header class="header">
    <h1>Full archive</h1>
    <p class="meta">Older Bing wallpapers (full resolution). <a href="../">Back to recent gallery</a>.</p>
  </header>
  <div class="grid">
"""

TAIL = """
  </div>
</body>
</html>
"""


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    append_entry_from_env(root)
    json_path = os.path.join(root, ARCHIVE_JSON)
    html_path = os.path.join(root, ARCHIVE_HTML)
    if not os.path.isfile(json_path):
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        with open(html_path, "w") as f:
            f.write(HEAD)
            f.write("\n    <p class=\"meta\">No archive entries yet.</p>\n")
            f.write(TAIL)
        return 0
    with open(json_path, "r") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        entries = []
    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, "w") as f:
        f.write(HEAD)
        for e in reversed(entries):
            url = e.get("url", "")
            date_str = e.get("date", "")
            title = e.get("title", e.get("key", "Image"))
            title_esc = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            f.write(f'    <div class="card"><a href="{url}" target="_blank" rel="noopener">')
            f.write(f'<span class="card-title">{title_esc}</span>')
            f.write(f'<span class="card-date">{date_str}</span></a></div>\n')
        f.write(TAIL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
