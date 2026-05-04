"""Public user-facing API endpoints (/v1/...).

All routes here require a valid JWT via `require_user`. Routes that
also need admin powers live in admin_routes.py.
"""
import time
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ...api.dependencies import require_user
from ...core.services.deals_service import (
    fetch_featured,
    search_game_live,
    get_price_history,
)
from ...data.repositories.crawler_repo import (
    get_crawler_setting,
    upsert_crawler_setting,
)
from ...data.repositories.deals_repo import (
    get_deal_by_id,
    update_thumbnail_for_deal,
)
from ...data.storage import (
    r2_is_configured,
    r2_object_exists,
    r2_presigned_get,
    upload_file_to_r2,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Identity / current user
# ---------------------------------------------------------------------------


@router.get("/me")
async def me(user=Depends(require_user)):
    """Return the authenticated user. Frontends should use this instead of
    decoding the JWT client-side: it's the source of truth for `is_admin`
    and lets us add fields like preferences later without re-signing."""
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
    }


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------


@router.get("/deals/featured")
async def featured(limit: int = 20, user=Depends(require_user)):
    return await fetch_featured(limit=limit)


@router.get("/deals/search")
async def search(title: str, pageSize: int = 60, user=Depends(require_user)):
    return await search_game_live(title=title, pageSize=pageSize)


@router.get("/deals/{deal_id}/history")
async def history(deal_id: str, limit: int = 50, user=Depends(require_user)):
    return await get_price_history(deal_id, limit=limit)


# ---------------------------------------------------------------------------
# Thumbnails: lazy R2 mirror
# ---------------------------------------------------------------------------
#
# The spider records each deal's `thumbnail_url` (CheapShark CDN URL).
# Rather than scraping more pages, we lazily mirror that image to R2 the
# first time a client asks for it. Subsequent calls return a presigned
# R2 URL with no upstream fetch. This means:
#   - Zero extra load on the spider.
#   - Bandwidth/egress is paid by Cloudflare R2 (free egress) instead of
#     CheapShark's CDN, which keeps us off their radar at scale.


_THUMBNAIL_PREFIX = "thumbnails"
_THUMBNAIL_TTL = 3600  # presigned URL validity, in seconds


def _thumbnail_key(deal_id: str) -> str:
    # deal_ids are short alphanumerics from CheapShark / our own
    # ("epic-<slug>", etc). Sanitize defensively.
    safe = "".join(c for c in deal_id if c.isalnum() or c in ("-", "_", "."))
    return f"{_THUMBNAIL_PREFIX}/{safe}.jpg"


@router.get("/deals/{deal_id}/thumbnail")
async def thumbnail(deal_id: str, user=Depends(require_user)):
    """Return a presigned R2 URL for this deal's thumbnail.

    Falls back to the original CheapShark CDN URL if R2 isn't configured
    or the upstream image can't be fetched. The response shape is always
    `{"url": "https://..."}` so the frontend doesn't need to branch.
    """
    deal = await get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    source_url: Optional[str] = deal.get("thumbnail_url")

    # No R2 wiring? Just hand back whatever URL we have.
    if not r2_is_configured():
        if not source_url:
            raise HTTPException(status_code=404, detail="No thumbnail available")
        return {"url": source_url, "source": "origin"}

    key = _thumbnail_key(deal_id)

    # Already cached in R2 → presign and return.
    if r2_object_exists(key):
        return {"url": r2_presigned_get(key, expires_in=_THUMBNAIL_TTL),
                "source": "r2"}

    # Not cached: fetch from origin and mirror.
    if not source_url:
        raise HTTPException(status_code=404, detail="No thumbnail available")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            data = resp.content
    except Exception as exc:
        # Origin fetch failed - return the source URL so the frontend
        # still shows something.
        return {"url": source_url, "source": "origin", "warning": str(exc)}

    try:
        upload_file_to_r2(bucket=None, key=key, data=data, content_type=content_type)
    except Exception as exc:
        # R2 upload failed (bucket misconfigured, network blip) - again,
        # fall back rather than fail the request.
        return {"url": source_url, "source": "origin", "warning": str(exc)}

    return {"url": r2_presigned_get(key, expires_in=_THUMBNAIL_TTL),
            "source": "r2"}


# ---------------------------------------------------------------------------
# Currency / exchange rate
# ---------------------------------------------------------------------------
#
# CheapShark prices are USD only. To show PHP (or any other currency) we
# fetch a USD->X rate from the free open.er-api.com endpoint and cache
# it for 24h in crawler_settings. No API key required.


_FX_CACHE_KEY_TEMPLATE = "_fx:{base}:{target}"
_FX_CACHE_TTL_SECONDS = 24 * 60 * 60
_FX_API = "https://open.er-api.com/v6/latest/{base}"


def _fx_supported(currency: str) -> bool:
    return currency.isalpha() and 2 <= len(currency) <= 5


@router.get("/exchange-rate")
async def exchange_rate(base: str = "USD", target: str = "PHP",
                        user=Depends(require_user)) -> Dict[str, Any]:
    """USD -> target FX rate, cached 24h.

    Default target is PHP since the app is built for a PH audience, but
    any ISO 4217 code accepted by open.er-api.com will work.
    """
    base = base.upper()
    target = target.upper()
    if not (_fx_supported(base) and _fx_supported(target)):
        raise HTTPException(status_code=400, detail="Invalid currency code")

    cache_key = _FX_CACHE_KEY_TEMPLATE.format(base=base, target=target)
    cached_raw = await get_crawler_setting(cache_key)
    if cached_raw:
        try:
            ts_str, rate_str = cached_raw.split("|", 1)
            ts = int(ts_str)
            rate = float(rate_str)
            if time.time() - ts < _FX_CACHE_TTL_SECONDS:
                return {
                    "base": base,
                    "target": target,
                    "rate": rate,
                    "fetched_at": datetime.utcfromtimestamp(ts).isoformat() + "Z",
                    "cached": True,
                }
        except (ValueError, TypeError):
            # cache poisoned, fall through to refresh
            pass

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(_FX_API.format(base=base))
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"Exchange rate fetch failed: {exc}")

    rates = data.get("rates") or {}
    rate = rates.get(target)
    if rate is None:
        raise HTTPException(status_code=404,
                            detail=f"No rate for {base}->{target}")

    now = int(time.time())
    try:
        await upsert_crawler_setting(cache_key, f"{now}|{rate}")
    except Exception:
        pass  # cache miss next call - not fatal

    return {
        "base": base,
        "target": target,
        "rate": float(rate),
        "fetched_at": datetime.utcfromtimestamp(now).isoformat() + "Z",
        "cached": False,
    }
