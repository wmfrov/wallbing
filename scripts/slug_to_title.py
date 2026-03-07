#!/usr/bin/env python3
"""
Convert a filename slug to a human-readable title.
E.g. AmboseliGiraffes_EN-US9072366924_UHD -> Amboseli Giraffes.
Strip _EN-US* and _UHD; insert space before capital letters.
"""
import re
import sys


def slug_to_title(slug: str) -> str:
    """Convert slug (basename without extension) to title."""
    if not slug:
        return slug
    # Remove extension if present
    base = slug
    while "." in base and base.rsplit(".", 1)[1].lower() in ("jpg", "png", "jpeg"):
        base = base.rsplit(".", 1)[0]
    # Strip locale and quality suffix: _EN-US1234567890_UHD or _UHD
    base = re.sub(r"_EN-US[0-9]+", "", base)
    base = re.sub(r"_UHD$", "", base)
    # Insert space before capital letters (CamelCase -> Title Case)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)  # ABC -> A BC
    return spaced.strip() if spaced else base


def main():
    if len(sys.argv) > 1:
        print(slug_to_title(sys.argv[1]))
    else:
        for line in sys.stdin:
            line = line.strip()
            if line:
                print(slug_to_title(line))


if __name__ == "__main__":
    main()
