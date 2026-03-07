'''
Download the Bing image of the day and save to disk.
Uses HPImageArchive JSON API. Runs once and exits. Schedule via cron or a loop (see README).
'''

import os
import re
import sys
import shutil
from datetime import datetime, timezone
import requests

OUTPUT_DIR = os.environ.get("BING_OUTPUT_DIR", "outputs")
REQUEST_TIMEOUT = int(os.environ.get("BING_REQUEST_TIMEOUT", "30"))
BING_BASE = "https://www.bing.com"
HPIMAGEARCHIVE_URL = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=en-US"

# Match resolution suffix in API url path, e.g. _1920x1080.jpg or _1366x768.jpg
RESOLUTION_PATTERN = re.compile(r"_\d+x\d+\.jpg", re.IGNORECASE)


def task():
    '''
    Fetch Bing image of the day from HPImageArchive API, download image, save to OUTPUT_DIR.
    Writes .title and .date sidecars from API. Returns True on success, False on failure.
    '''
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        r = requests.get(HPIMAGEARCHIVE_URL, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.Timeout:
        print("Error: timed out requesting HPImageArchive API", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error: failed to fetch HPImageArchive API: {e}", file=sys.stderr)
        return False

    try:
        data = r.json()
    except ValueError as e:
        print(f"Error: invalid JSON from API: {e}", file=sys.stderr)
        return False

    images = data.get("images")
    if not images or len(images) < 1:
        print("Error: no images in HPImageArchive response", file=sys.stderr)
        return False

    info = images[0]
    url_path = info.get("url") or ""
    urlbase = info.get("urlbase") or ""

    if not url_path:
        print("Error: missing url in API response", file=sys.stderr)
        return False

    # Build UHD image URL: replace resolution suffix with _UHD.jpg
    url_path_uhd = RESOLUTION_PATTERN.sub("_UHD.jpg", url_path)
    image_url = BING_BASE + url_path_uhd

    # Derive local filename from urlbase (e.g. /th?id=OHR.Name_EN-US123 -> Name_EN-US123.png)
    if "OHR." in urlbase:
        base = urlbase.split("OHR.", 1)[-1].strip()
    else:
        # Fallback: strip resolution from url path and take id part
        base = RESOLUTION_PATTERN.sub("", url_path)
        if "id=OHR." in base:
            base = base.split("OHR.", 1)[-1].split("&")[0]
        else:
            base = base.replace("/", "_").replace("?", "_")
    if not base:
        print("Error: could not derive filename from API response", file=sys.stderr)
        return False
    file_name = base + "_UHD.png"

    file_path = os.path.join(OUTPUT_DIR, file_name)
    print("Image URL:", image_url)
    print("Saving to:", file_path)

    try:
        response = requests.get(image_url, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        print("Error: timed out downloading image", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error: failed to download image: {e}", file=sys.stderr)
        return False

    try:
        with open(file_path, "wb") as out_file:
            shutil.copyfileobj(response.raw, out_file)
    except OSError as e:
        print(f"Error: failed to write file: {e}", file=sys.stderr)
        return False

    # Date from API startdate (YYYYMMDD -> YYYY-MM-DD); fallback: today
    startdate = info.get("startdate")
    if startdate and len(startdate) >= 8:
        date_str = f"{startdate[:4]}-{startdate[4:6]}-{startdate[6:8]}"
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_path = os.path.join(OUTPUT_DIR, file_name + ".date")
    try:
        with open(date_path, "w") as f:
            f.write(date_str)
    except OSError:
        pass

    print("Saved:", file_path)
    return True


def main():
    if task():
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
