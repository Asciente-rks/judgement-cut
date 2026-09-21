# Scrapers (Scrapy)

The Scrapy project that powers Judgement Cut's daily crawl. One spider (`games`) cycles through CheapShark for Steam / GOG / Humble and Epic's `freeGamesPromotions` endpoint, then POSTs results to the FastAPI backend in batches of 25 via the `ScraperIngestPipeline`. At end-of-run it calls `/internal/ingest/finalize` so the backend can re-enrich, deactivate, and prune stale rows.

## Layout

```
scrapers/
├── scrapy.cfg
├── scrapinghub.yml         # Zyte project ID (currently 860207)
├── setup.py
├── requirements.txt        # scrapy>=2.8, shub, requests
├── deploy.bat              # one-click shub deploy from the project root
├── .env.example            # BACKEND_INGEST_URL + SCRAPER_SECRET
└── scrapers/
    ├── items.py            # DealItem schema
    ├── settings.py         # CONCURRENT_REQUESTS=1, DOWNLOAD_DELAY=2, polite UA
    ├── pipelines.py        # ScraperIngestPipeline — batches of 25 + finalize call
    └── spiders/
        └── games_spider.py # CheapShark (Steam/GOG/Humble) + Epic free games
```

## Environment

Set these in Zyte's project Spider Settings (or via a local `.env` for development):

| Variable | Purpose |
|----------|---------|
| `BACKEND_INGEST_URL` | Full URL to the Lambda's `/internal/ingest` endpoint |
| `SCRAPER_SECRET` | Shared secret — must match the Lambda's `SCRAPER_SECRET` env var |

Without both set the pipeline drops every item and logs an error.

## Running locally

```bash
cd scrapers
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill in BACKEND_INGEST_URL + SCRAPER_SECRET
scrapy crawl games
```

## Deploying to Zyte Scrapy Cloud

```bash
pip install shub
shub login                  # paste your Zyte API key when prompted
shub deploy                 # uses scrapinghub.yml
```

`deploy.bat` does the same thing on Windows — it just forces the working directory to the project root before invoking `shub`.

After deploy, set `BACKEND_INGEST_URL` and `SCRAPER_SECRET` in the Zyte project's **Spider Settings** panel. Zyte injects those as Scrapy settings (not OS environment variables) at run time.

## Why concurrency = 1

Zyte's Free Forever plan gives you a single Scrapy Cloud Unit, so requests are processed serially anyway. `CONCURRENT_REQUESTS = 1` + `DOWNLOAD_DELAY = 2` keeps the crawl polite and avoids triggering CheapShark's anti-abuse layer mid-run.

## Daily scheduling

The cron lives in `.github/workflows/run-spider-daily.yml` at the repo root — not in Zyte. The workflow fires at 18:00 UTC (02:00 PHT), hits Zyte's `run.json` REST endpoint with `SHUB_API_KEY`, and queues a job. This avoids paying for Scrapy Cloud's Periodic Jobs feature and uses ~1 minute/day from the GitHub Actions free tier.
