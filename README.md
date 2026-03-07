# Bing image of the day → wallpapers

A small app that downloads [Bing’s daily image](https://www.bing.com) and can publish it to a GitHub Pages gallery and/or save it locally for wallpaper rotation.

## What it does

- Fetches the current Bing image of the day (UHD).
- Can run **once** and exit (no long-lived daemon); you schedule it via cron, Docker, or GitHub Actions.
- Handles missing network without crashing; exits with a non-zero code so schedulers can retry.
- Optional **GitHub Actions** workflow: runs on a schedule, downloads the image, and deploys a gallery to the **gh-pages** branch so it’s viewable at `https://<username>.github.io/<repo>/`.

## Quick start (local)

```bash
pip install -r requirements.txt
mkdir -p outputs
python app.py
```

The image is saved under `outputs/` (or set `BING_OUTPUT_DIR`).

## Running in Docker

- **One-off run:**  
  `docker compose build && docker compose run --rm myapp`  
  (mount a volume in `docker-compose.yaml` so the image is written where you want.)

- **Scheduled (every 6 hours) in a long-running container:**  
  `docker compose --profile scheduled up -d bing_scheduled`

## GitHub Actions + Pages

The repo includes a workflow that:

1. Runs on a schedule (e.g. every 6 hours) and on manual “Run workflow”.
2. Downloads the Bing image (full resolution), builds a static gallery page, and pushes to the **gh-pages** branch.
3. Keeps the gallery under ~300 MB by evicting the **oldest images by date** when over the cap (FIFO). Dates come from metadata (download date for new images; existing images use a dummy date if none was stored).
4. GitHub Pages serves that branch as a gallery.

**Setup:**

1. Push the repo to GitHub (including `.github/workflows/download-bing-image.yml`).
2. In the repo: **Settings → Pages → Source** → **Deploy from a branch** → branch **gh-pages**.
3. Run the workflow once from the Actions tab (or wait for the schedule). The gallery will be at `https://<username>.github.io/<repo>/`.

Bing updates the image **once per day**; the workflow runs every 6 hours so it picks up the new image soon after it’s available.

## Seeding the gallery from local images

To replace or seed the gh-pages gallery with a sample of your own local wallpapers (e.g. from `~/Pictures/bingimages`), up to ~300 MB, newest-first by file date:

```bash
chmod +x scripts/upload-local-images-to-pages.sh
./scripts/upload-local-images-to-pages.sh [local_images_dir]
```

Default source is `LOCAL_IMAGES` or `~/Pictures/bingimages`. The script copies full-resolution images, creates thumbnails, writes `metadata.json` (using file mtime as date, or a dummy date when unavailable), builds the index, then prompts before force-pushing to **gh-pages**. Requires ImageMagick (`convert`) and Python 3.

## Syncing the gallery to your computer

If you use the GitHub Pages gallery, you can pull those same images to a folder for wallpaper rotation:

```bash
chmod +x scripts/sync-wallpapers-from-pages.sh
./scripts/sync-wallpapers-from-pages.sh [destination_folder]
```

With no argument, images are synced into `~/Pictures/bingimages`. The script copies all image types (e.g. `.png`, `.jpg`) from the gallery. Use that folder (or your chosen path) in **System Settings → Wallpaper** for rotation.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BING_OUTPUT_DIR` | `outputs` | Directory where the image is saved. |
| `BING_REQUEST_TIMEOUT` | `30` | HTTP request timeout (seconds). |
| `BING_INTERVAL_SECONDS` | `21600` | Seconds between runs when using the Docker “scheduled” profile (6 hours). |

## License

Use and modify as you like.
