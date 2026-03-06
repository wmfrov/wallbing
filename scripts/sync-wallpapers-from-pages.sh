#!/usr/bin/env bash
# Sync Bing wallpapers from the gh-pages branch into a local folder for wallpaper rotation.
# Uses a cache dir for the clone; copies only images into DEST.
#
# Usage: ./scripts/sync-wallpapers-from-pages.sh [destination_dir]
#
# Default destination: ~/Pictures/bingimages (images are copied directly into this folder)
# Set BING_PAGES_REPO to override the repo URL.

set -e

REPO_URL="${BING_PAGES_REPO:-https://github.com/wmfrov/wallbing.git}"
DEST="${1:-$HOME/Pictures/bingimages}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/wallbing-gh-pages"

mkdir -p "$DEST"
mkdir -p "$(dirname "$CACHE_DIR")"

if [[ -d "$CACHE_DIR/.git" ]]; then
  echo "Pulling latest from gh-pages into cache..."
  (cd "$CACHE_DIR" && git fetch origin gh-pages && git reset --hard origin/gh-pages)
else
  echo "Cloning gh-pages into cache..."
  rm -rf "$CACHE_DIR"
  git clone --single-branch --branch gh-pages --depth 1 "$REPO_URL" "$CACHE_DIR"
fi

echo "Copying images to $DEST ..."
mkdir -p "$CACHE_DIR/images"
cp -n "$CACHE_DIR"/images/*.png "$DEST/" 2>/dev/null || true

COUNT=$(find "$DEST" -maxdepth 1 -name '*.png' 2>/dev/null | wc -l)
echo "Done. $COUNT image(s) in $DEST"
echo "Use this folder for wallpaper rotation: $DEST"
