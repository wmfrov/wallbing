#!/bin/sh
# Run the download every INTERVAL_SECONDS (default 21600 = 6 hours).
# When no network: task fails, we log and sleep; no crash.
INTERVAL_SECONDS="${BING_INTERVAL_SECONDS:-21600}"

while true; do
  if python /app/app.py; then
    echo "Download completed successfully."
  else
    echo "Download failed (e.g. no network). Will retry in ${INTERVAL_SECONDS}s."
  fi
  sleep "$INTERVAL_SECONDS"
done
