'''
Download the Bing image of the day and save to disk.
Runs once and exits. Schedule via cron or a loop (see README).
'''

import os
import sys
import shutil
import requests

OUTPUT_DIR = os.environ.get("BING_OUTPUT_DIR", "outputs")
REQUEST_TIMEOUT = int(os.environ.get("BING_REQUEST_TIMEOUT", "30"))
BING_URL = "https://www.bing.com"


def generic_snip(input_str, start_index_str, end_index_str):
    '''
    Trims a string between two substrings.
    Returns the substring after start_index_str and before end_index_str.
    '''
    start_index = input_str.find(start_index_str)
    if start_index == -1:
        return ""
    input_str = input_str[start_index:]
    end_index = input_str.find(end_index_str)
    if end_index == -1:
        return input_str
    return input_str[:end_index]


def find_image_name(html: str):
    '''
    Extract the Bing image of the day URL from the page HTML.
    Returns None if the expected pattern is not found.
    '''
    output = generic_snip(html, 'meta property="og:image"', '/>')
    if not output:
        return None
    output = generic_snip(output, 'content', 'rf=')
    if not output:
        return None
    output = generic_snip(output, 'h', '_tmb')
    if not output:
        return None
    return output + '_UHD.jpg'


def find_file_name(image_url: str):
    '''
    Convert the image URL to a local filename.
    '''
    output = generic_snip(image_url, 'OHR.', '.jpg')
    if not output:
        return None
    return output[4:] + '.png'


def find_og_title(html: str):
    '''
    Extract og:title from the page HTML for use as the image title.
    Returns None if not found. May strip a leading "Bing – " for cleaner display.
    '''
    chunk = generic_snip(html, 'property="og:title"', '/>')
    if not chunk:
        return None
    chunk = generic_snip(chunk, 'content="', '"')
    if not chunk:
        return None
    # Optional: strip Bing prefix for a shorter gallery title
    if chunk.startswith("Bing – ") or chunk.startswith("Bing - "):
        chunk = chunk[7:].strip()
    return chunk.strip() if chunk else None


def task():
    '''
    Fetch Bing homepage, find image URL, download image, save to OUTPUT_DIR.
    Returns True on success, False on failure. Does not raise.
    '''
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Fetch Bing page
    try:
        r = requests.get(BING_URL, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.Timeout:
        print("Error: timed out requesting Bing HTML", file=sys.stderr)
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error: failed to fetch Bing page: {e}", file=sys.stderr)
        return False

    image_url = find_image_name(r.text)
    if not image_url:
        print("Error: could not find image URL in Bing page", file=sys.stderr)
        return False

    file_name = find_file_name(image_url)
    if not file_name:
        print("Error: could not derive filename from image URL", file=sys.stderr)
        return False

    file_path = os.path.join(OUTPUT_DIR, file_name)
    print("Image URL:", image_url)
    print("Saving to:", file_path)

    # Download image
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

    # Write optional title sidecar for gallery metadata (e.g. images/Photo.png.title)
    title = find_og_title(r.text)
    if title:
        title_path = os.path.join(OUTPUT_DIR, file_name + ".title")
        try:
            with open(title_path, "w") as f:
                f.write(title)
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
