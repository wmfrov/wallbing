#!/usr/bin/env bash
# Upload your local Bing images to the gh-pages branch so the gallery shows a full trove.
# Run once to seed the gallery, or whenever you want to add more local images.
#
# Usage: ./scripts/upload-local-images-to-pages.sh
#
# Copies from: LOCAL_IMAGES (default: ~/Pictures/bingimages)
# Pushes to:   BING_PAGES_REPO, branch gh-pages

set -e

REPO_URL="${BING_PAGES_REPO:-https://github.com/wmfrov/wallbing.git}"
LOCAL_IMAGES="${LOCAL_IMAGES:-$HOME/Pictures/bingimages}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -d "$LOCAL_IMAGES" ]]; then
  echo "Error: Local images dir not found: $LOCAL_IMAGES"
  echo "Set LOCAL_IMAGES or create that folder and add images."
  exit 1
fi

COUNT=$(find "$LOCAL_IMAGES" -maxdepth 1 -name '*.png' 2>/dev/null | wc -l)
if [[ "$COUNT" -eq 0 ]]; then
  echo "Error: No .png files in $LOCAL_IMAGES"
  exit 1
fi

echo "Found $COUNT image(s) in $LOCAL_IMAGES"
TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

echo "Cloning gh-pages into temp dir..."
if ! git clone --single-branch --branch gh-pages --depth 1 "$REPO_URL" "$TMP" 2>/dev/null; then
  echo "gh-pages branch not found. Creating it from main..."
  git clone --depth 1 "$REPO_URL" "$TMP"
  cd "$TMP"
  git checkout --orphan gh-pages
  git rm -rf . 2>/dev/null || true
  cd - >/dev/null
fi

echo "Copying images..."
mkdir -p "$TMP/images"
cp -n "$LOCAL_IMAGES"/*.png "$TMP/images/" 2>/dev/null || true

echo "Generating gallery index..."
cp "$REPO_ROOT/scripts/gallery-index-head.html" "$TMP/index.html"
for f in "$TMP"/images/*.png; do
  [[ -f "$f" ]] || continue
  name=$(basename "$f")
  base="${name%.*}"
  echo "    <div class=\"card\"><a href=\"images/$name\" target=\"_blank\" title=\"$base\"><img src=\"images/$name\" alt=\"$base\" loading=\"lazy\"><span>$base</span></a></div>" >> "$TMP/index.html"
done
cat "$REPO_ROOT/scripts/gallery-index-tail.html" >> "$TMP/index.html"

cd "$TMP"
git add .
git status
echo "Commit and push? (y/n)"
read -r yn
if [[ "$yn" != "y" && "$yn" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "Add local Bing wallpaper trove"
git push origin gh-pages
echo "Done. Gallery updated at gh-pages."