"""Spider <-> backend internal endpoints.

Gated by the X-Scraper-Secret header. The spider POSTs deal items here;
the admin monitor reads back a heartbeat so we can tell from the UI
whether the spider is reaching us.

For Steam deals (store_id == "1") we also enrich with Steam's native
regional pricing (PHP) via store.steampowered.com/api/appdetails.
That bypasses the inaccurate USD * FX conversion CheapShark would
otherwise force on us.

End-of-run finalize: at the end of each crawl, the spider POSTs to
/internal/ingest/finalize with the run's start time. We then mark any
deal whose `last_seen_at` is older than that as inactive, so stale
deals from previous runs (deals that have come off sale) don't keep
showing up in the dashboard's "live deals" count.
"""
import time

from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from ..core import config
from ..core.services.steam_pricing import fetch_steam_regional_price
from ..data.repositories.crawler_repo import upsert_crawler_setting
from ..data.repositories.deals_repo import (
    insert_featured_deal,
    mark_stale_deals_inactive,
    update_regional_pricing,
)
from ..data.repositories.price_history_repo import insert_price_record

router = APIRouter()


# crawler_settings keys used as a heartbeat. Any successful /ingest call
# updates these; the admin scraper-monitor endpoint reads them back.
LAST_INGEST_AT_KEY = "_last_ingest_at"
LAST_INGEST_COUNT_KEY = "_last_ingest_count"
LAST_FINALIZE_AT_KEY = "_last_finalize_at"
LAST_FINALIZE_DEACTIVATED_KEY = "_last_finalize_deactivated"

# Steam store ID in CheapShark's universe.
_STEAM_STORE_ID = "1"


def _normalize_thumbnail(value):
    """The CheapShark `thumb` field is a URL string. Reject anything else."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith("http") else None


def _normalize_steam_app_id(value):
    """CheapShark `steamAppID` is a numeric string. Anything non-digit -> None."""
    if value in (None, "", 0):
        return None
    s = str(value).strip()
    return s if s.isdigit() else None


async def _enrich_steam_pricing(deal_id: str, app_id: str) -> None:
    """Fetch native PHP pricing from Steam and persist on the deal.

    Failures are swallowed: if Steam is unreachable / returns no
    price_overview / the app is region-locked, we leave price_php=NULL
    and the frontend falls back to USD * FX. This is intentionally
    fire-and-forget at the call site - we don't want spider POSTs to
    block on a slow Steam API.
    """
    try:
        price = await fetch_steam_regional_price(app_id, country_code="PH")
    except Exception:
        return
    if price is None:
        return
    try:
        await update_regional_pricing(
            deal_id,
            price_php=price.final,
            normal_price_php=price.initial,
        )
    except Exception:
        return


@router.post("/ingest")
async def ingest(request: Request, x_scraper_secret: Optional[str] = Header(None)):
    # Validate secret
    if not config.SCRAPER_SECRET:
        raise HTTPException(status_code=500, detail="Scraper secret not configured on server")
    if x_scraper_secret != config.SCRAPER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid scraper secret")

    payload = await request.json()
    # Accept either a list of items (batched, normal path) or a single
    # item (legacy / per-item POSTs from older spider versions).
    items = payload if isinstance(payload, list) else [payload]

    inserted = 0
    for it in items:
        # Map fields expected by featured_deals table. The spider sends
        # `thumbnail_url` (CheapShark's `thumb`) and `steam_app_id`
        # (CheapShark's `steamAppID`); the bare CheapShark response uses
        # `thumb` / `steamAppID`; tolerate both for forwards-compat.
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
            "steam_app_id": _normalize_steam_app_id(
                it.get("steam_app_id") or it.get("steamAppID")
            ),
        }
        try:
            # `insert_featured_deal` also stamps last_seen_at=NOW() and
            # is_active=1 on the row, which lets the finalize step below
            # tell stale rows (not seen this run) apart from current ones.
            await insert_featured_deal(deal)
            if deal.get("deal_id") and deal.get("price") is not None:
                await insert_price_record(deal.get("deal_id"), deal.get("price"))
            inserted += 1
        except Exception:
            # continue on errors to be robust
            continue

        # Steam-only enrichment with native PHP pricing. Synchronous so
        # that by the time /v1/deals/featured returns, the row has the
        # accurate price. ~200-400ms per Steam deal; spider has 30s
        # timeout per POST and we batch 25 items, so we're well within
        # budget (worst case ~10s per batch on a Steam-heavy run).
        if (deal.get("store_id") == _STEAM_STORE_ID
                and deal.get("steam_app_id")
                and deal.get("deal_id")):
            await _enrich_steam_pricing(deal["deal_id"], deal["steam_app_id"])

    # Heartbeat: record when the spider last reached us and how much it
    # delivered. Counts items in the latest batch only - the admin
    # monitor sums these across the day if needed.
    try:
        now_iso = str(int(time.time()))
        await upsert_crawler_setting(LAST_INGEST_AT_KEY, now_iso)
        await upsert_crawler_setting(LAST_INGEST_COUNT_KEY, str(inserted))
    except Exception:
        # Heartbeat failure shouldn't poison the ingest call.
        pass

    return {"inserted": inserted}


@router.post("/ingest/finalize")
async def finalize(request: Request, x_scraper_secret: Optional[str] = Header(None)):
    """Mark deals not seen in this crawl as inactive.

    The spider POSTs `{"run_started_at": <epoch_seconds>}` after all
    items have been ingested. Any deal whose `last_seen_at` is NULL or
    older than `run_started_at` is set is_active=0, which removes it
    from the dashboard's "live deals" view.

    This is what fixes the "Sync status: 662 live deals but spider
    only scraped 422" inconsistency. Old deals from previous runs that
    came off sale (and so weren't included in the latest crawl) get
    cleaned up here.
    """
    if not config.SCRAPER_SECRET:
        raise HTTPException(status_code=500, detail="Scraper secret not configured on server")
    if x_scraper_secret != config.SCRAPER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid scraper secret")

    payload = await request.json()
    run_started_at = payload.get("run_started_at")
    if not isinstance(run_started_at, (int, float)) or run_started_at <= 0:
        raise HTTPException(
            status_code=400,
            detail="run_started_at must be a positive epoch timestamp",
        )

    try:
        deactivated = await mark_stale_deals_inactive(int(run_started_at))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finalize failed: {e}")

    # Update heartbeat keys so the admin monitor can show when the last
    # crawl finished and how many deals were retired.
    try:
        await upsert_crawler_setting(LAST_FINALIZE_AT_KEY, str(int(time.time())))
        await upsert_crawler_setting(LAST_FINALIZE_DEACTIVATED_KEY, str(deactivated))
    except Exception:
        pass

    return {"deactivated": deactivated, "run_started_at": int(run_started_at)}
