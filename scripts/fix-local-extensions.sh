#!/usr/bin/env bash
# Fix file extensions in the local Bing images directory.
# Renames .png and doubled .jpg.jpg (etc.) files to a single .jpg.
# Dry-run by default; pass --apply to actually rename.
#
# Usage:
#   ./scripts/fix-local-extensions.sh [--apply] [directory]
#   Default directory: ~/Pictures/bingimages

set -e

APPLY=false
DIR=""

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=true ;;
    *) DIR="$arg" ;;
  esac
done

DIR="${DIR:-$HOME/Pictures/bingimages}"

if [[ ! -d "$DIR" ]]; then
  echo "Error: directory not found: $DIR"
  exit 1
fi

normalize() {
  local name="$1"
  while [[ "$name" == *.jpg || "$name" == *.png ]]; do
    name="${name%.jpg}"
    name="${name%.png}"
  done
  echo "${name}.jpg"
}

count=0
skipped=0

while IFS= read -r -d '' filepath; do
  filename=$(basename "$filepath")
  target=$(normalize "$filename")

  [[ "$filename" == "$target" ]] && continue

  target_path="$DIR/$target"

  if [[ -f "$target_path" ]]; then
    echo "[SKIP] $filename -> $target (target already exists)"
    skipped=$(( skipped + 1 ))
    continue
  fi

  if $APPLY; then
    mv "$filepath" "$target_path"
    echo "[RENAMED] $filename -> $target"
  else
    echo "[DRY RUN] $filename -> $target"
  fi
  count=$(( count + 1 ))
done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.png" -o -iname "*.jpg" \) -print0)

if $APPLY; then
  echo "Renamed $count file(s). Skipped $skipped collision(s)."
else
  echo "Would rename $count file(s). Skipped $skipped collision(s). Run with --apply to execute."
fi
