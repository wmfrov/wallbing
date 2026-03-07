#!/usr/bin/env bash
# Seed or replace the gh-pages gallery with a sample of local images: up to ~300 MB
# chosen newest-first by file mtime (full resolution). Uses a dummy date (2000-01-01)
# when mtime isn't available. Builds metadata.json and index, then force-pushes to gh-pages.
#
# Usage: ./scripts/upload-local-images-to-pages.sh [local_images_dir]
#
# Default: LOCAL_IMAGES or ~/Pictures/bingimages
# Requires: ImageMagick (convert), Python 3, git. Run from repo root.

set -e

TARGET_BYTES=$((300 * 1024 * 1024))
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_IMAGES="${1:-${LOCAL_IMAGES:-$HOME/Pictures/bingimages}}"
DEPLOY="$REPO_ROOT/deploy_pages_upload"
SCRIPT_DIR="$REPO_ROOT/scripts"

if [[ ! -d "$LOCAL_IMAGES" ]]; then
  echo "Error: directory not found: $LOCAL_IMAGES"
  exit 1
fi

# Collect image files (input: lines "bytes date_str name"); cap by total size
accumulate() {
  local total=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    read -r bytes date_str name <<< "$line"
    if (( total + bytes > TARGET_BYTES )); then
      break
    fi
    total=$(( total + bytes ))
    echo "$line"
  done
}

echo "Scanning $LOCAL_IMAGES (newest first, cap ~300 MB)..."
# Output: bytes YYYY-MM-DD name (one line per file)
list_all() {
  find "$LOCAL_IMAGES" -maxdepth 1 -type f \( -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" \) -print0 | \
  while IFS= read -r -d '' f; do
    name=$(basename "$f")
    [[ -z "$name" ]] && continue
    bytes=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
    mtime=$(stat -f%m "$f" 2>/dev/null || stat -c%Y "$f" 2>/dev/null || echo 0)
    if [[ "$mtime" -gt 0 ]]; then
      date_str=$(date -r "$mtime" +%Y-%m-%d 2>/dev/null || date -d "@$mtime" +%Y-%m-%d 2>/dev/null || echo "2000-01-01")
    else
      date_str="2000-01-01"
    fi
    echo "$bytes $date_str $name"
  done
}

SELECTED=$(list_all | sort -t' ' -k2,2r -k3,3 | accumulate)

mkdir -p "$DEPLOY/images" "$DEPLOY/thumbs"
total=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  read -r bytes date_str name <<< "$line"
  src="$LOCAL_IMAGES/$name"
  if [[ ! -f "$src" ]]; then continue; fi
  cp "$src" "$DEPLOY/images/$name"
  if command -v convert &>/dev/null; then
    convert "$src" -resize 400x400\> -quality 82 "$DEPLOY/thumbs/${name}.jpg"
  fi
  total=$(( total + bytes ))
done <<< "$SELECTED"

echo "$SELECTED" | python3 "$SCRIPT_DIR/write-gallery-metadata.py" "$DEPLOY" > "$DEPLOY/sorted.txt"

echo "Selected $(echo "$SELECTED" | grep -c . || true) images (~$(( total / 1024 / 1024 )) MB). Building index..."

cp "$SCRIPT_DIR/gallery-index-head.html" "$DEPLOY/index.html"
while IFS= read -r key; do
  [[ -z "$key" ]] || [[ ! -f "$DEPLOY/$key" ]] && continue
  name=$(basename "$key")
  base="${name%.*}"
  echo "    <div class=\"card\"><a href=\"$key\" target=\"_blank\" title=\"$base\"><img src=\"thumbs/${name}.jpg\" alt=\"$base\" loading=\"lazy\"><span>$base</span></a></div>" >> "$DEPLOY/index.html"
done < "$DEPLOY/sorted.txt"
cat "$SCRIPT_DIR/gallery-index-tail.html" >> "$DEPLOY/index.html"

echo "Publishing to gh-pages..."
cd "$REPO_ROOT"
# Stash local changes so checkout gh-pages doesn't fail
STASHED=
if ! git diff --quiet || ! git diff --cached --quiet; then
  git stash push -u -m "upload-local-images-to-pages: temp stash"
  STASHED=1
fi
git fetch origin
if git show-ref --verify --quiet refs/remotes/origin/gh-pages 2>/dev/null; then
  git checkout gh-pages
  git pull origin gh-pages 2>/dev/null || true
  git rm -rf . 2>/dev/null || true
else
  git checkout --orphan gh-pages
  git rm -rf . 2>/dev/null || true
fi
cp -r "$DEPLOY"/* .
rm -rf "$DEPLOY"
git add .
git status
echo "Commit and force-push? (y/N)"
read -r confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
  git commit -m "Gallery: upload local sample (~300 MB, newest by date)"
  git push origin gh-pages --force
  echo "Done. Gallery updated on gh-pages."
else
  echo "Aborted. Changes are in the working tree (gh-pages)."
fi
# Return to main before popping stash so stash (main's state) applies to main, not gh-pages
git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
[[ -n "$STASHED" ]] && git stash pop
