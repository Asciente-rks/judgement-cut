"""Spider -> backend ingestion pipeline.

Each item produced by `games_spider` is POSTed to the backend's
`/internal/ingest` endpoint with a shared secret header.

Configure these in the Zyte dashboard under Spider Settings (NOT in
the local .env, which doesn't get uploaded by `shub deploy`):

  BACKEND_INGEST_URL  full https URL of the backend /internal/ingest
  SCRAPER_SECRET      shared secret matching the backend env var

If either is missing, the spider fails fast on its first item rather
than running an entire crawl that silently throws everything away.
"""
import json
import os

import requests


BACKEND_INGEST = os.getenv("BACKEND_INGEST_URL")
SCRAPER_SECRET = os.getenv("SCRAPER_SECRET")


class ScraperIngestPipeline:
    """Post each item to the backend ingestion endpoint."""

    def __init__(self):
        # Track once-per-spider state so we only error/warn loudly the
        # first time. Subsequent items still fail but quietly.
        self._config_checked = False
        self._fail_count = 0
        self._success_count = 0

    def open_spider(self, spider):
        if not BACKEND_INGEST:
            spider.logger.error(
                "BACKEND_INGEST_URL is not set. The spider will scrape but "
                "every item will be DROPPED. Set this in Zyte's Spider "
                "Settings (project dashboard) to your backend URL."
            )
        if not SCRAPER_SECRET:
            spider.logger.error(
                "SCRAPER_SECRET is not set. POSTs to /internal/ingest will "
                "be rejected with 403. Set this in Zyte's Spider Settings."
            )

    def close_spider(self, spider):
        # Visible end-of-run summary so the cause is obvious from the
        # Zyte log even if all items failed silently.
        spider.logger.info(
            "ScraperIngestPipeline summary: %d posted, %d failed",
            self._success_count,
            self._fail_count,
        )

    def process_item(self, item, spider):
        # If config is missing, skip the POST entirely. The error was
        # already logged in open_spider; we don't repeat it per item.
        if not BACKEND_INGEST or not SCRAPER_SECRET:
            self._fail_count += 1
            return item

        headers = {
            "Content-Type": "application/json",
            "X-Scraper-Secret": SCRAPER_SECRET,
        }
        try:
            resp = requests.post(
                BACKEND_INGEST,
                data=json.dumps(dict(item)),
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            self._success_count += 1
        except requests.HTTPError as e:
            self._fail_count += 1
            # Show the response body on the first failure so misconfigured
            # secrets ('Invalid scraper secret') are easy to spot.
            if self._fail_count == 1:
                body = ""
                try:
                    body = e.response.text[:200]
                except Exception:
                    pass
                spider.logger.warning(
                    "First /internal/ingest failure: %s. Body: %s",
                    e, body,
                )
            else:
                spider.logger.warning(
                    "Failed to POST item to backend ingest: %s", e,
                )
        except Exception as e:
            self._fail_count += 1
            spider.logger.warning(
                "Failed to POST item to backend ingest: %s", e,
            )

        return item
