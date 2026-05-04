"""Spider <-> backend internal endpoints.

Gated by the X-Scraper-Secret header. The spider POSTs deal items here;
the admin monitor reads back a heartbeat so we can tell from the UI
whether the spider is reaching us.

For Steam deals (store_id == "1") we also enrich with Steam's native
regional pricing (PHP) via store.steampowered.com/api/appdetails.
That bypasses the inaccurate USD * FX conversion CheapShark would
otherwise force on us.

End-of-run finalize: at the end of each crawl, the spider POSTs to
/internal/ingest/finalize with the run's start time. The finalize
endpoint runs three phases in order:

  1. Re-enrichment retry: any active Steam deal still missing native
     PHP pricing gets another attempt at fetch_steam_regional_price.
     Catches deals where the in-line ingest enrichment hit a transient
     Steam API failure (so the user doesn't see USD-converted fallback
     prices that don't match Steam PH).
  2. Mark inactive: any deal whose last_seen_at is older than the run's
     start time (or NULL) gets is_active=0.
  3. Delete inactive: rows with is_active=0 are removed entirely so
     the table row count matches the latest crawl. Price history is
     preserved separately.

Together these fix two user-reported issues:
  - "system price doesn't match Steam PH" -> retry enrichment
  - "TiDB row count grows forever, doesn't match Zyte" -> delete inactive
"""
import asyncio
import time

from fastapi import APIRouter, Header, HTTPException, Request
from typing import Optional

from ..core import config
from ..core.services.steam_pricing import fetch_steam_regional_price
from ..data.repositories.crawler_repo import upsert_crawler_setting
from ..data.repositories.deals_repo import (
    delete_stale_deals,
    get_active_deals_needing_enrichment,
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
LAST_FINALIZE_DELETED_KEY = "_last_finalize_deleted"
LAST_FINALIZE_REENRICHED_KEY = "_last_finalize_reenriched"  # "succeeded/attempted"

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


# Concurrent Steam enrichment within a single ingest batch. Steam's
# regional API is the slowest part of /ingest (~300ms-3s per call,
# including retries). Running 25 calls sequentially blows the Lambda
# 30s timeout. Running 5 concurrently keeps a 25-deal batch well under
# 10s typical, ~15s worst case.
_INGEST_ENRICHMENT_CONCURRENCY = 5


async def _enrich_with_semaphore(
    sem: asyncio.Semaphore, deal_id: str, app_id: str
) -> None:
    """Run _enrich_steam_pricing under a semaphore for bounded concurrency."""
    async with sem:
        await _enrich_steam_pricing(deal_id, app_id)


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
    steam_enrich_targets = []  # list of (deal_id, app_id) tuples
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

        # Queue Steam-only enrichment with native PHP pricing. We don't
        # call it inline here - if we did, 25 sequential Steam API calls
        # at ~1-3s each (especially with retries) would blow the Lambda
        # 30s timeout. Instead we collect the deals to enrich and fire
        # them concurrently below.
        if (deal.get("store_id") == _STEAM_STORE_ID
                and deal.get("steam_app_id")
                and deal.get("deal_id")):
            steam_enrich_targets.append((deal["deal_id"], deal["steam_app_id"]))

    # Concurrent Steam enrichment for the whole batch. asyncio.gather
    # with a 5-way semaphore gives us bounded parallelism: max 5
    # in-flight Steam API calls at once, so we respect Steam's rate
    # limits but don't serialize the whole batch. With 25 deals at 5
    # concurrent and ~1s typical per call, this finishes in ~5s instead
    # of ~25s sequential.
    if steam_enrich_targets:
        sem = asyncio.Semaphore(_INGEST_ENRICHMENT_CONCURRENCY)
        await asyncio.gather(
            *(
                _enrich_with_semaphore(sem, deal_id, app_id)
                for deal_id, app_id in steam_enrich_targets
            ),
            return_exceptions=True,  # one bad enrich shouldn't poison the batch
        )

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


# Cap on Phase-1 enrichment retries so finalize fits in the Lambda 30s
# budget. With 5 concurrent workers and ~3-4s per Steam call (incl. its
# own retries), 50 deals takes ~30-40s worst case, ~10s typical.
_FINALIZE_ENRICHMENT_LIMIT = 50
_FINALIZE_ENRICHMENT_CONCURRENCY = 5


async def _retry_enrichment_for_row(sem: asyncio.Semaphore, row: dict) -> bool:
    """Re-attempt Steam regional pricing for one row. Returns True on success.

    Used by the finalize endpoint's Phase 1. Failures are swallowed -
    one bad row shouldn't poison the whole finalize call.
    """
    app_id = row.get("steam_app_id")
    deal_id = row.get("deal_id")
    if not app_id or not deal_id:
        return False
    async with sem:
        try:
            price = await fetch_steam_regional_price(app_id, country_code="PH")
        except Exception:
            return False
        if price is None:
            return False
        try:
            await update_regional_pricing(
                deal_id,
                price_php=price.final,
                normal_price_php=price.initial,
            )
            return True
        except Exception:
            return False


@router.post("/ingest/finalize")
async def finalize(request: Request, x_scraper_secret: Optional[str] = Header(None)):
    """Run the three-phase end-of-crawl finalize.

      Phase 1: re-enrich active Steam deals where price_php is still NULL.
      Phase 2: mark deals not seen in this run as inactive.
      Phase 3: delete inactive rows so the table = latest crawl.

    The spider POSTs `{"run_started_at": <epoch_seconds>}` after all
    items have been ingested.
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

    # ------------------------------------------------------------------
    # Phase 1: re-attempt Steam enrichment for active deals with NULL
    # price_php. These are deals where the in-line enrichment during
    # /ingest hit a transient Steam API failure (timeout, 5xx) and
    # silently fell through to NULL. Without this retry, the frontend
    # falls back to USD x FX which doesn't match what Steam actually
    # shows in PH (the bug the user reported with NBA 2K26).
    #
    # Bounded to 50 deals at 5 concurrent so the whole finalize fits in
    # the Lambda 30s timeout even in the worst case.
    # ------------------------------------------------------------------
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
        # Don't let a Phase-1 failure block Phase-2/3 - the inactive
        # cleanup is more important than enrichment retries.
        pass

    # ------------------------------------------------------------------
    # Phase 2: mark stale deals inactive.
    # ------------------------------------------------------------------
    try:
        deactivated = await mark_stale_deals_inactive(int(run_started_at))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Finalize failed: {e}")

    # ------------------------------------------------------------------
    # Phase 3: delete inactive rows so the table row count matches the
    # latest crawl. CheapShark assigns fresh dealIDs for new promotions,
    # so we won't lose anything important - the same game on its next
    # sale will come back with a new dealID. Price history (separate
    # table, no FK) is preserved for historical lookup.
    # ------------------------------------------------------------------
    deleted = 0
    try:
        deleted = await delete_stale_deals()
    except Exception:
        # Same logic as Phase 1 - don't fail finalize on cleanup error.
        # The next run will retry the cleanup.
        pass

    # Update heartbeat keys so the admin monitor can show when the last
    # crawl finished and how many deals were retired / cleaned up.
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
