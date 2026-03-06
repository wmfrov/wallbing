#!/usr/bin/env bash
# Compare local Bing images with what's on gh-pages. Reports counts and lists
# any files missing from the remote (so you can re-run the upload or fix issues).
#
# Usage: ./scripts/audit-local-vs-pages.sh [local_dir]
# Default local_dir: ~/Pictures/bingimages

set -e

LOCAL_IMAGES="${1:-$HOME/Pictures/bingimages}"
REPO_URL="${BING_PAGES_REPO:-https://github.com/wmfrov/wallbing.git}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -d "$LOCAL_IMAGES" ]]; then
  echo "Error: $LOCAL_IMAGES not found."
  exit 1
fi

echo "Local folder: $LOCAL_IMAGES"
echo "Remote:       gh-pages of $REPO_URL"
echo ""

# Local basenames (e.g. WaveDenmark_EN-US6550970747_UHD.png)
local_list=$(mktemp)
trap "rm -f $local_list" EXIT
find "$LOCAL_IMAGES" -maxdepth 1 -name '*.png' -exec basename {} \; | sort -u > "$local_list"
local_count=$(wc -l < "$local_list")

# Clone gh-pages and list images
TMP=$(mktemp -d)
trap "rm -rf $TMP; rm -f $local_list" EXIT
if ! git clone --single-branch --branch gh-pages --depth 1 "$REPO_URL" "$TMP" 2>/dev/null; then
  echo "Could not clone gh-pages. Is the branch created and pushed?"
  exit 1
fi

remote_list=$(mktemp)
trap "rm -rf $TMP; rm -f $local_list $remote_list" EXIT
find "$TMP/images" -name '*.png' 2>/dev/null | xargs -I {} basename {} | sort -u > "$remote_list"
remote_count=$(wc -l < "$remote_list")

# Missing from remote (on local but not on gh-pages)
missing=$(comm -23 "$local_list" "$remote_list")
missing_count=$(echo "$missing" | grep -c . || true)

# On remote but not local (optional info)
extra=$(comm -13 "$local_list" "$remote_list")
extra_count=$(echo "$extra" | grep -c . || true)

echo "Local:  $local_count image(s)"
echo "Remote: $remote_count image(s)"
echo ""

if [[ "$missing_count" -gt 0 ]]; then
  echo "Missing on remote ($missing_count):"
  echo "$missing" | sed 's/^/  /'
  echo ""
  echo "Re-run the upload script to add them: ./scripts/upload-local-images-to-pages.sh"
else
  echo "All local images are on gh-pages."
fi

if [[ "$extra_count" -gt 0 ]]; then
  echo ""
  echo "On remote but not in $LOCAL_IMAGES ($extra_count) — e.g. from workflow:"
  echo "$extra" | sed 's/^/  /' | head -20
  [[ "$extra_count" -gt 20 ]] && echo "  ... and $(( extra_count - 20 )) more"
fi
