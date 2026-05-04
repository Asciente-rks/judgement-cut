"""Spider -> backend ingestion pipeline.

Items produced by `games_spider` are batched and POSTed to the backend's
`/internal/ingest` endpoint with a shared secret header. At end of crawl
we also POST `/internal/ingest/finalize` to mark deals not seen in this
run as inactive (so the dashboard's "live deals" count reflects the
latest crawl, not historical accumulation).

Where to set the two config values:

  Zyte Cloud   -> project dashboard -> Spider Settings (or Job Settings)
                Settings get injected as Scrapy settings, NOT env vars.
  Local dev    -> either export env vars before `scrapy crawl games`, or
                add them to scrapy `settings.py`.

This pipeline reads from `crawler.settings` first (works on Zyte) and
falls back to os.environ (works locally without changing settings.py).
If neither has them, every item is dropped with a loud error log so
the failure mode is impossible to miss.

Batching rationale:
  Per-item POST = 1 Lambda invocation per deal = ~700/day = ~21k/month.
  Batched POST  = 25 deals/POST = ~30/day = ~900/month.
  That's a ~23x reduction, freeing the user's 1M/month free tier for
  other apps. The Steam enrichment path inside the backend takes ~300ms
  per Steam deal, so 25 Steam items per batch ~= 7.5s of enrichment +
  insertions, well within Lambda's 30s timeout.
"""
import json
import os
import time

import requests


# How many items to buffer before flushing to the backend.
# 25 is a compromise between Lambda invocation count (lower is better)
# and per-batch latency (higher batches risk Lambda 30s timeout when
# all items need Steam enrichment).
BATCH_SIZE = 25

# Per-POST timeout. The original was 10s but a full Steam-heavy batch
# can take 8-12s on the backend, so we give it more headroom.
POST_TIMEOUT_SECONDS = 30


class ScraperIngestPipeline:
    """Batch items and POST them to the backend ingestion endpoint."""

    def __init__(self, ingest_url: str, scraper_secret: str):
        self.ingest_url = ingest_url
        self.scraper_secret = scraper_secret
        self._fail_count = 0
        self._success_count = 0
        # Cache the warning state so we only ever log the configuration
        # error once, not per-item.
        self._warned_missing = False
        self._buffer = []
        # Epoch seconds at the start of the crawl; sent to /finalize so
        # the backend can mark deals not seen in this run as inactive.
        self._run_started_at = None

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
        # Flush whatever's left in the buffer so partial batches at the
        # tail of the run still make it to the backend.
        if self._buffer:
            self._flush(spider)

        # Tell the backend to mark deals not seen in this run as inactive.
        # This fixes the "system shows 662 live deals but spider only
        # scraped 422" inconsistency: stale entries from prior runs that
        # are no longer on sale get is_active=0 and disappear from the
        # featured-deals API.
        if self.ingest_url and self.scraper_secret and self._run_started_at:
            self._post_finalize(spider)

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
            # Show response body on the first failure so misconfigured
            # secrets ('Invalid scraper secret') are easy to spot.
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
        """Tell the backend the crawl is done. It marks any deal whose
        last_seen_at is older than this run's start time as inactive.

        Best-effort: we don't fail the run on a finalize error. The
        finalize endpoint is on the same Lambda as /ingest, so if
        /ingest worked, /finalize should too.
        """
        # Derive the finalize URL from the ingest URL (just swap the
        # path suffix). The spider treats them as a tightly-coupled pair
        # so users only need to set BACKEND_INGEST_URL once.
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
