#!/usr/bin/env python3
"""
Convert a filename slug to a human-readable title.
E.g. AmboseliGiraffes_EN-US9072366924_UHD.jpg -> Amboseli Giraffes.
Strip extension, _EN-US*, and _UHD; insert space before capital letters.
"""
import re
import sys


def slug_to_title(slug: str) -> str:
    """Convert slug (filename) to title."""
    if not slug:
        return slug
    base = slug.rsplit(".", 1)[0] if "." in slug else slug
    base = re.sub(r"_EN-US[0-9]+", "", base)
    base = re.sub(r"_UHD$", "", base)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
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
