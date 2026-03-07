#!/usr/bin/env bash
# Upload ALL local Bing images to gh-pages gallery.
# Newest images (by mtime) are hosted full-res until ~860 MB budget is reached.
# Remaining images are "archived": only thumbnails are hosted, full-res links to Bing CDN.
# All .png files are renamed to .jpg (they're actually JPEG data).
#
# Usage: ./scripts/upload-local-images-to-pages.sh [local_images_dir]
#
# Default: LOCAL_IMAGES or ~/Pictures/bingimages
# Requires: ImageMagick (convert), Python 3, git. Run from repo root.

set -e

TARGET_BYTES=$((860 * 1024 * 1024))
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_IMAGES="${1:-${LOCAL_IMAGES:-$HOME/Pictures/bingimages}}"
DEPLOY="$REPO_ROOT/deploy_pages_upload"
SCRIPT_DIR="$REPO_ROOT/scripts"

if [[ ! -d "$LOCAL_IMAGES" ]]; then
  echo "Error: directory not found: $LOCAL_IMAGES"
  exit 1
fi

normalize_name() {
  local name="$1"
  while [[ "$name" == *.jpg || "$name" == *.png ]]; do
    name="${name%.jpg}"
    name="${name%.png}"
  done
  echo "${name}.jpg"
}

echo "Scanning $LOCAL_IMAGES..."
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

ALL_IMAGES=$(list_all | sort -t' ' -k2,2r -k3,3)
TOTAL_COUNT=$(echo "$ALL_IMAGES" | grep -c . || true)
echo "Found $TOTAL_COUNT images."

rm -rf "$DEPLOY"
mkdir -p "$DEPLOY/images" "$DEPLOY/thumbs"

hosted_total=0
hosted_count=0
archived_count=0
META_LINES=""

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  read -r bytes date_str orig_name <<< "$line"
  src="$LOCAL_IMAGES/$orig_name"
  if [[ ! -f "$src" ]]; then continue; fi

  name=$(normalize_name "$orig_name")

  if command -v convert &>/dev/null; then
    convert "$src" -resize 400x400\> -quality 82 "$DEPLOY/thumbs/${name}.jpg" 2>/dev/null || true
  fi

  if (( hosted_total + bytes <= TARGET_BYTES )); then
    cp "$src" "$DEPLOY/images/$name"
    hosted_total=$(( hosted_total + bytes ))
    hosted_count=$(( hosted_count + 1 ))
    META_LINES+="$bytes $date_str hosted $name"$'\n'
  else
    archived_count=$(( archived_count + 1 ))
    META_LINES+="0 $date_str archived $name"$'\n'
  fi
done <<< "$ALL_IMAGES"

echo "$META_LINES" | python3 "$SCRIPT_DIR/write-gallery-metadata.py" "$DEPLOY" > "$DEPLOY/sorted.txt"

echo "Hosted: $hosted_count (~$(( hosted_total / 1024 / 1024 )) MB), Archived: $archived_count (Bing CDN). Building index..."

cp "$SCRIPT_DIR/gallery-index-head.html" "$DEPLOY/index.html"
while IFS=$'\t' read -r key date_str title_str href; do
  [[ -z "$key" ]] && continue
  name=$(basename "$key")
  title_str="${title_str:-${name%.*}}"
  echo "    <div class=\"card\"><a href=\"$href\" target=\"_blank\" title=\"$title_str\"><img src=\"thumbs/${name}.jpg\" alt=\"$title_str\" loading=\"lazy\"><span class=\"card-title\">$title_str</span><span class=\"card-date\">${date_str:-}</span></a></div>" >> "$DEPLOY/index.html"
done < "$DEPLOY/sorted.txt"
cat "$SCRIPT_DIR/gallery-index-tail.html" >> "$DEPLOY/index.html"

echo "Publishing to gh-pages..."
cd "$REPO_ROOT"
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
  git commit -m "Gallery: all $TOTAL_COUNT images (hosted: $hosted_count, archived: $archived_count)"
  git push origin gh-pages --force
  echo "Done. Gallery updated on gh-pages."
else
  echo "Aborted. Changes are in the working tree (gh-pages)."
fi
git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
[[ -n "$STASHED" ]] && git stash pop
