"""Spider -> backend ingestion pipeline.

Each item produced by `games_spider` is POSTed to the backend's
`/internal/ingest` endpoint with a shared secret header.

Where to set the two config values:

  Zyte Cloud  → project dashboard → Spider Settings (or Job Settings)
                Settings get injected as Scrapy settings, NOT env vars.
  Local dev   → either export env vars before `scrapy crawl games`, or
                add them to scrapy `settings.py`.

This pipeline reads from `crawler.settings` first (works on Zyte) and
falls back to os.environ (works locally without changing settings.py).
If neither has them, every item is dropped with a loud error log so
the failure mode is impossible to miss.
"""
import json
import os

import requests


class ScraperIngestPipeline:
    """Post each item to the backend ingestion endpoint."""

    def __init__(self, ingest_url: str, scraper_secret: str):
        self.ingest_url = ingest_url
        self.scraper_secret = scraper_secret
        self._fail_count = 0
        self._success_count = 0
        # Cache the warning state so we only ever log the configuration
        # error once, not per-item.
        self._warned_missing = False

    @classmethod
    def from_crawler(cls, crawler):
        """Read config from Scrapy settings (Zyte's path) or env (local)."""
        settings = crawler.settings
        ingest_url = (
            settings.get("BACKEND_INGEST_URL")
            or os.getenv("BACKEND_INGEST_URL")
        )
        scraper_secret = (
            settings.get("SCRAPER_SECRET")
            or os.getenv("SCRAPER_SECRET")
        )
        return cls(ingest_url, scraper_secret)

    def open_spider(self, spider):
        if not self.ingest_url:
            spider.logger.error(
                "BACKEND_INGEST_URL is not set. The spider will scrape but "
                "every item will be DROPPED. Set this in Zyte's Spider "
                "Settings (project dashboard) - it gets injected as a "
                "Scrapy setting, NOT as an environment variable."
            )
        if not self.scraper_secret:
            spider.logger.error(
                "SCRAPER_SECRET is not set. POSTs to /internal/ingest will "
                "be rejected with 403. Set it in Zyte's Spider Settings "
                "(must match the SCRAPER_SECRET env var on Lambda)."
            )

    def close_spider(self, spider):
        spider.logger.info(
            "ScraperIngestPipeline summary: %d posted, %d failed",
            self._success_count,
            self._fail_count,
        )

    def process_item(self, item, spider):
        # Bail early if config is missing - error already logged at startup.
        if not self.ingest_url or not self.scraper_secret:
            self._fail_count += 1
            return item

        headers = {
            "Content-Type": "application/json",
            "X-Scraper-Secret": self.scraper_secret,
        }
        try:
            resp = requests.post(
                self.ingest_url,
                data=json.dumps(dict(item)),
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            self._success_count += 1
        except requests.HTTPError as e:
            self._fail_count += 1
            # Show response body on the first failure so misconfigured
            # secrets ('Invalid scraper secret') are easy to spot.
            if self._fail_count == 1:
                body = ""
                try:
                    body = e.response.text[:200] if e.response is not None else ""
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
