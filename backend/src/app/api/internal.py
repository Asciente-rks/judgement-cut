
import asyncio
import time

from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from ..core import config
from ..core.services.steam_pricing import (
    fetch_steam_regional_price,
    search_steam_appid_by_title,
)
from ..data.repositories.crawler_repo import upsert_crawler_setting
from ..data.repositories.deals_repo import (
    delete_stale_deals,
    get_active_deals_needing_enrichment,
    insert_featured_deal,
    mark_stale_deals_inactive,
    update_regional_pricing,
    update_steam_app_id,
)
from ..data.repositories.price_history_repo import insert_price_record

router = APIRouter()

LAST_INGEST_AT_KEY = "_last_ingest_at"
LAST_INGEST_COUNT_KEY = "_last_ingest_count"
LAST_FINALIZE_AT_KEY = "_last_finalize_at"
LAST_FINALIZE_DEACTIVATED_KEY = "_last_finalize_deactivated"
LAST_FINALIZE_DELETED_KEY = "_last_finalize_deleted"
LAST_FINALIZE_REENRICHED_KEY = "_last_finalize_reenriched"

_STEAM_STORE_ID = "1"

def _normalize_thumbnail(value):

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith("http") else None

def _normalize_steam_app_id(value):

    if value in (None, "", 0):
        return None
    s = str(value).strip()
    return s if s.isdigit() else None

async def _enrich_steam_pricing(
    deal_id: str,
    app_id: Optional[str],
    title: Optional[str] = None,
) -> None:

    if not app_id and title:
        recovered = await search_steam_appid_by_title(title)
        if recovered:
            app_id = recovered

            try:
                await update_steam_app_id(deal_id, recovered)
            except Exception:

                pass

    if not app_id:
        return

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

_INGEST_ENRICHMENT_CONCURRENCY = 5

async def _enrich_with_semaphore(
    sem: asyncio.Semaphore,
    deal_id: str,
    app_id: Optional[str],
    title: Optional[str],
) -> None:

    async with sem:
        await _enrich_steam_pricing(deal_id, app_id, title)

@router.post("/ingest")
async def ingest(request: Request, x_scraper_secret: Optional[str] = Header(None)):

    if not config.SCRAPER_SECRET:
        raise HTTPException(status_code=500, detail="Scraper secret not configured on server")
    if x_scraper_secret != config.SCRAPER_SECRET:
        raise HTTPException(status_code=403, detail="Invalid scraper secret")

    payload = await request.json()

    items = payload if isinstance(payload, list) else [payload]

    inserted = 0
    steam_enrich_targets = []
    for it in items:

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

            await insert_featured_deal(deal)
            if deal.get("deal_id") and deal.get("price") is not None:
                await insert_price_record(deal.get("deal_id"), deal.get("price"))
            inserted += 1
        except Exception:

            continue

        if (deal.get("store_id") == _STEAM_STORE_ID
                and deal.get("deal_id")):
            steam_enrich_targets.append((
                deal["deal_id"],
                deal.get("steam_app_id"),
                deal.get("title"),
            ))

    if steam_enrich_targets:
        sem = asyncio.Semaphore(_INGEST_ENRICHMENT_CONCURRENCY)
        await asyncio.gather(
            *(
                _enrich_with_semaphore(sem, deal_id, app_id, title)
                for deal_id, app_id, title in steam_enrich_targets
            ),
            return_exceptions=True,
        )

    try:
        now_iso = str(int(time.time()))
        await upsert_crawler_setting(LAST_INGEST_AT_KEY, now_iso)
        await upsert_crawler_setting(LAST_INGEST_COUNT_KEY, str(inserted))
    except Exception:

        pass

    return {"inserted": inserted}

_FINALIZE_ENRICHMENT_LIMIT = 50
_FINALIZE_ENRICHMENT_CONCURRENCY = 5

async def _retry_enrichment_for_row(sem: asyncio.Semaphore, row: dict) -> bool:

    deal_id = row.get("deal_id")
    if not deal_id:
        return False
    app_id = row.get("steam_app_id")
    title = row.get("title")
    if not app_id and not title:

        return False
    async with sem:
        try:
            await _enrich_steam_pricing(deal_id, app_id, title)
        except Exception:
            return False

    return True

@router.post("/ingest/finalize")
async def finalize(request: Request, x_scraper_secret: Optional[str] = Header(None)):

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

    enrichment_attempted = 0
    enrichment_succeeded = 0
    try:
        needing = await get_active_deals_needing_enrichment(
            limit=_FINALIZE_ENRICHMENT_LIMIT,
        )
        if needing:
            sem = asyncio.Semaphore(_FINALIZE_ENRICHMENT_CONCURRENCY)
            results = await asyncio.gather(
                *(_retry_enrichment_for_row(sem, row) for row in needing),
                return_exceptions=True,
            )
            enrichment_attempted = len(results)
            enrichment_succeeded = sum(1 for r in results if r is True)
    except Exception:

        pass

    try:
        deactivated = await mark_stale_deals_inactive(int(run_started_at))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finalize failed: {e}")

    deleted = 0
    try:
        deleted = await delete_stale_deals()
    except Exception:

        pass

    try:
        await upsert_crawler_setting(LAST_FINALIZE_AT_KEY, str(int(time.time())))
        await upsert_crawler_setting(LAST_FINALIZE_DEACTIVATED_KEY, str(deactivated))
        await upsert_crawler_setting(LAST_FINALIZE_DELETED_KEY, str(deleted))
        await upsert_crawler_setting(
            LAST_FINALIZE_REENRICHED_KEY,
            f"{enrichment_succeeded}/{enrichment_attempted}",
        )
    except Exception:
        pass

    return {
        "deactivated": deactivated,
        "deleted": deleted,
        "enrichment_attempted": enrichment_attempted,
        "enrichment_succeeded": enrichment_succeeded,
        "run_started_at": int(run_started_at),
    }
