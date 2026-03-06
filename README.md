# Bing image of the day downloader

Downloads the Bing image of the day and saves it to a folder (e.g. for wallpaper rotation).

## Improvements

- **Run once and exit** – No long-running Python/schedule loop; you choose how to schedule.
- **Robust to no internet** – All request and I/O errors are caught; the process exits with code 1 and does not crash.
- **Multiple ways to run** – Host cron, long-running container, or GitHub Actions + Pages (no server at all).

## Option A: Host cron (good for a single machine)

Run the container once every 6 hours from cron. No container runs between executions.

1. Build the image:
   ```bash
   docker compose build
   ```

2. Add a cron job (run `crontab -e`):
   ```cron
   0 */6 * * * cd /Users/will.ziegler/projects/newbingapp && docker compose run --rm myapp
   ```

Replace the path with your project directory. When there’s no internet, the run fails and cron will try again at the next interval.

## Option B: Long-running container

One container that runs the download every 6 hours and sleeps in between. If a run fails (e.g. no network), it logs and retries at the next interval.

```bash
docker compose --profile scheduled up -d bing_scheduled
```

To change the interval (default 6 hours), set `BING_INTERVAL_SECONDS` (e.g. `43200` for 12 hours).

---

## Option C: GitHub Actions + GitHub Pages (no server, free)

**GitHub Pages only serves static files** (HTML, CSS, JS, images). It does not run Python or any code. So “run on GitHub Pages” means:

- **GitHub Actions** runs on a schedule (e.g. every 6 hours), runs this app in the cloud, and pushes the new image (and a simple gallery page) to the `gh-pages` branch.
- **GitHub Pages** then serves that branch as a static site: your images plus an index page.

You get a public URL like `https://<username>.github.io/<repo>/` with a gallery of all collected images. No server to maintain; if a run fails (e.g. no network in the runner), the next run tries again.

1. Push this repo to GitHub (including `.github/workflows/download-bing-image.yml`).
2. In the repo: **Settings → Pages → Source**: set to **Deploy from a branch**; branch **gh-pages** (create the branch if needed, e.g. empty commit and push).
3. The workflow runs every 6 hours and on **Actions → Run workflow**. After the first run, your site will be at `https://<username>.github.io/<repo>/`.

---

## Other reasonable methods

| Method | Best for |
|--------|----------|
| **systemd timer** (Linux) | Running the script or container on a schedule on your own Linux box; survives reboots. |
| **Launchd** (macOS) | Same idea on a Mac: run the script or `docker run` on a schedule. |
| **Cloud cron + serverless** (e.g. AWS EventBridge + Lambda, GCP Cloud Scheduler + Cloud Function) | Running in the cloud on a schedule without a long-lived server; more setup. |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BING_OUTPUT_DIR` | `outputs` | Directory where images are saved (use `/app/outputs` in Docker and mount a volume). |
| `BING_REQUEST_TIMEOUT` | `30` | Timeout in seconds for HTTP requests. |
| `BING_INTERVAL_SECONDS` | `21600` | Seconds between runs when using `entrypoint.sh` (Option B). |

## Local run (no Docker)

```bash
pip install -r requirements.txt
mkdir -p outputs
python app.py
```

To run every 6 hours locally, use cron or a systemd timer pointing at `python /path/to/app.py`.
