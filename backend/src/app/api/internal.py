"""Spider <-> backend internal endpoints.

Gated by the X-Scraper-Secret header. The spider POSTs deal items here;
the admin monitor reads back a heartbeat so we can tell from the UI
whether the spider is reaching us.
"""
import time
from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from ..core import config
from ..data.repositories.crawler_repo import upsert_crawler_setting
from ..data.repositories.deals_repo import insert_featured_deal
from ..data.repositories.price_history_repo import insert_price_record

router = APIRouter()


# crawler_settings keys used as a heartbeat. Any successful /ingest call
# updates these; the admin scraper-monitor endpoint reads them back.
LAST_INGEST_AT_KEY = "_last_ingest_at"
LAST_INGEST_COUNT_KEY = "_last_ingest_count"


def _normalize_thumbnail(value):
    """The CheapShark `thumb` field is a URL string. Reject anything else."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith("http") else None


@router.post("/ingest")
async def ingest(request: Request, x_scraper_secret: Optional[str] = Header(None)):
    # Validate secret
    if not config.SCRAPER_SECRET:
        raise HTTPException(status_code=500, detail="Scraper secret not configured on server")
    if x_scraper_secret != config.SCRAPER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid scraper secret")

    payload = await request.json()
    # Accept either a list of items or a single item
    items = payload if isinstance(payload, list) else [payload]

    inserted = 0
    for it in items:
        # Map fields expected by featured_deals table. The spider sends
        # `thumbnail_url` (CheapShark's `thumb`); the bare CheapShark
        # response uses `thumb`; tolerate both for forwards-compat.
        deal = {
            "deal_id": it.get("deal_id") or it.get("dealID") or it.get("id"),
            "title": it.get("title"),
            "store_id": it.get("store") or it.get("storeID") or it.get("store_id"),
            "price": float(it.get("price")) if it.get("price") is not None else None,
            "normal_price": float(it.get("normal_price") or it.get("normalPrice") or 0),
            "deal_rating": float(it.get("deal_rating") or 0.0),
            "thumbnail_url": _normalize_thumbnail(
                it.get("thumbnail_url") or it.get("thumb") or it.get("thumbnail")
            ),
        }
        try:
            await insert_featured_deal(deal)
            if deal.get("deal_id") and deal.get("price") is not None:
                await insert_price_record(deal.get("deal_id"), deal.get("price"))
            inserted += 1
        except Exception:
            # continue on errors to be robust
            continue

    # Heartbeat: record when the spider last reached us and how much it
    # delivered. The admin monitor surfaces this so the operator can tell
    # at a glance whether the pipeline is alive.
    try:
        now_iso = str(int(time.time()))
        await upsert_crawler_setting(LAST_INGEST_AT_KEY, now_iso)
        await upsert_crawler_setting(LAST_INGEST_COUNT_KEY, str(inserted))
    except Exception:
        # Heartbeat failure shouldn't poison the ingest call.
        pass

    return {"inserted": inserted}
