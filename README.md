# wallbing

A daily Bing image-of-the-day gallery on GitHub Pages, plus a local wallpaper fetcher for macOS.

## Gallery (GitHub Actions + Pages)

A GitHub Actions workflow runs daily, fetches the latest images from the Bing API, and publishes a static gallery to the `gh-pages` branch. All images are served directly from Bing's CDN -- nothing is downloaded or hosted in the repo.

**How it works:**

1. The workflow checks out the repo and runs `build_gallery.py`.
2. The script clones `gh-pages`, loads the existing `metadata.json` (the cumulative list of all known images), and fetches the latest 8 entries from the Bing API.
3. It rebuilds `index.html` with thumbnail cards (`_400x240.jpg` CDN URLs) and a lightbox for full-resolution viewing (`_UHD.jpg` CDN URLs).
4. It commits and pushes back to `gh-pages`.

**Setup:**

1. Push the repo to GitHub.
2. In the repo: **Settings > Pages > Source** > **Deploy from a branch** > branch **gh-pages**.
3. Run the workflow once from the **Actions** tab, or wait for the daily schedule.

The gallery will be at `https://<username>.github.io/<repo>/`.

## Local wallpaper fetcher

`fetch_weekly.py` downloads the latest 8 Bing UHD images to `~/Pictures/bingimages` and maintains a local `images.txt` manifest (gitignored) to avoid re-downloading. Requires the `requests` package (`pip install requests`).

Run manually:

```bash
python3 fetch_weekly.py
```

Or schedule via launchd (runs every Monday at 9 AM):

```bash
cp com.wallbing.weekly.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wallbing.weekly.plist
```

The plist assumes the repo is cloned at `~/projects/wallbing`. Edit the path inside the plist if yours is different.

Use `~/Pictures/bingimages` as the wallpaper folder in **System Settings > Wallpaper** for automatic rotation.

## License

Use and modify as you like.
