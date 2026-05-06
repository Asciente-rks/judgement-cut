
import json
import os
import time

import requests

BATCH_SIZE = 25

POST_TIMEOUT_SECONDS = 30

class ScraperIngestPipeline:

    def __init__(self, ingest_url: str, scraper_secret: str):
        self.ingest_url = ingest_url
        self.scraper_secret = scraper_secret
        self._fail_count = 0
        self._success_count = 0

        self._warned_missing = False
        self._buffer = []

        self._run_started_at = None

    @classmethod
    def from_crawler(cls, crawler):

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
        self._run_started_at = int(time.time())
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

        if self._buffer:
            self._flush(spider)

        if self.ingest_url and self.scraper_secret and self._run_started_at:
            self._post_finalize(spider)

        spider.logger.info(
            "ScraperIngestPipeline summary: %d posted, %d failed",
            self._success_count,
            self._fail_count,
        )

    def process_item(self, item, spider):

        if not self.ingest_url or not self.scraper_secret:
            self._fail_count += 1
            return item

        self._buffer.append(dict(item))
        if len(self._buffer) >= BATCH_SIZE:
            self._flush(spider)
        return item

    def _flush(self, spider):
        if not self._buffer:
            return
        batch = self._buffer
        self._buffer = []

        headers = {
            "Content-Type": "application/json",
            "X-Scraper-Secret": self.scraper_secret,
        }
        try:
            resp = requests.post(
                self.ingest_url,
                data=json.dumps(batch),
                headers=headers,
                timeout=POST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            self._success_count += len(batch)
        except requests.HTTPError as e:
            self._fail_count += len(batch)

            body = ""
            try:
                body = e.response.text[:200] if e.response is not None else ""
            except Exception:
                pass
            spider.logger.warning(
                "Failed to POST batch of %d items to backend ingest: %s. Body: %s",
                len(batch), e, body,
            )
        except Exception as e:
            self._fail_count += len(batch)
            spider.logger.warning(
                "Failed to POST batch of %d items to backend ingest: %s",
                len(batch), e,
            )

    def _post_finalize(self, spider):

        if not self.ingest_url.endswith("/ingest"):
            spider.logger.warning(
                "BACKEND_INGEST_URL doesn't end with /ingest (%s); skipping "
                "finalize. Stale deals won't be marked inactive this run.",
                self.ingest_url,
            )
            return
        finalize_url = self.ingest_url[: -len("/ingest")] + "/ingest/finalize"

        headers = {
            "Content-Type": "application/json",
            "X-Scraper-Secret": self.scraper_secret,
        }
        try:
            resp = requests.post(
                finalize_url,
                data=json.dumps({"run_started_at": self._run_started_at}),
                headers=headers,
                timeout=POST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            spider.logger.info(
                "Finalize OK: marked stale deals inactive (run_started_at=%d)",
                self._run_started_at,
            )
        except Exception as e:
            spider.logger.warning(
                "Failed to POST /internal/ingest/finalize: %s. Stale deals "
                "from prior runs will remain marked active in the DB.",
                e,
            )
