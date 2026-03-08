# wallbing

A browsable gallery of every Bing image of the day, updated automatically and hosted on GitHub Pages.

**[View the gallery](https://wmfrov.github.io/wallbing/)**

## Gallery

1,755+ wallpapers from February 2021 to today, with a new image added daily. Every image is analyzed by AI to enable:

- **Filter by subject** -- landscape, animal, architecture, ocean, snow, aurora, and more
- **Freeform search** -- search for "coral reef", "red bridge", or "snowy village" and find matches even when those words aren't in the original title
- **Full-res viewing** -- click any image for a UHD lightbox with download

All images are served from Bing's CDN. Nothing is hosted in this repo.

For downloading Bing wallpapers locally, see [wallbing-fetcher](https://github.com/wmfrov/wallbing-fetcher).

## Setup

1. Push the repo to GitHub.
2. **Settings > Pages > Source** > branch `gh-pages`.
3. Add an `OPENAI_API_KEY` repository secret for automatic image tagging.
4. Run the workflow from the **Actions** tab, or wait for the daily schedule.

## Image disclaimer

All images are the property of Microsoft/Bing and their respective photographers, provided for personal non-commercial use. This project links to them on Bing's CDN and does not host or redistribute any images.

## License

[MIT License](LICENSE)
