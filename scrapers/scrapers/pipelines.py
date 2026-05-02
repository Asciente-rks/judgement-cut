import os
import requests
import json

BACKEND_INGEST = os.getenv('BACKEND_INGEST_URL', 'http://localhost:8000/internal/ingest')
SCRAPER_SECRET = os.getenv('SCRAPER_SECRET')


class ScraperIngestPipeline:
    """Post each item to the backend ingestion endpoint using the shared secret.

    Configure environment variables in Zyte or local shell:
      BACKEND_INGEST_URL - full URL to backend /internal/ingest
      SCRAPER_SECRET - shared secret header value
    """

    def process_item(self, item, spider):
        headers = {}
        if SCRAPER_SECRET:
            headers['X-Scraper-Secret'] = SCRAPER_SECRET

        try:
            # send as single-item list to allow bulk handling on backend
            resp = requests.post(BACKEND_INGEST, data=json.dumps(dict(item)), headers={**headers, 'Content-Type': 'application/json'}, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            spider.logger.warning(f"Failed to POST item to backend ingest: {e}")

        return item
