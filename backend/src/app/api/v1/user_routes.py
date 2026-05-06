
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

@router.get("/me")
async def me(user=Depends(require_user)):

    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
    }

@router.get("/deals/featured")
async def featured(limit: int = 20, user=Depends(require_user)):
    return await fetch_featured(limit=limit)

@router.get("/deals/search")
async def search(title: str, pageSize: int = 60, user=Depends(require_user)):
    return await search_game_live(title=title, pageSize=pageSize)

@router.get("/deals/{deal_id}/history")
async def history(deal_id: str, limit: int = 50, user=Depends(require_user)):
    return await get_price_history(deal_id, limit=limit)

_THUMBNAIL_PREFIX = "thumbnails"
_THUMBNAIL_TTL = 3600

def _thumbnail_key(deal_id: str) -> str:

    safe = "".join(c for c in deal_id if c.isalnum() or c in ("-", "_", "."))
    return f"{_THUMBNAIL_PREFIX}/{safe}.jpg"

@router.get("/deals/{deal_id}/thumbnail")
async def thumbnail(deal_id: str, user=Depends(require_user)):

    deal = await get_deal_by_id(deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    source_url: Optional[str] = deal.get("thumbnail_url")

    if not r2_is_configured():
        if not source_url:
            raise HTTPException(status_code=404, detail="No thumbnail available")
        return {"url": source_url, "source": "origin"}

    key = _thumbnail_key(deal_id)

    if r2_object_exists(key):
        return {"url": r2_presigned_get(key, expires_in=_THUMBNAIL_TTL),
                "source": "r2"}

    if not source_url:
        raise HTTPException(status_code=404, detail="No thumbnail available")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            data = resp.content
    except Exception as exc:

        return {"url": source_url, "source": "origin", "warning": str(exc)}

    try:
        upload_file_to_r2(bucket=None, key=key, data=data, content_type=content_type)
    except Exception as exc:

        return {"url": source_url, "source": "origin", "warning": str(exc)}

    return {"url": r2_presigned_get(key, expires_in=_THUMBNAIL_TTL),
            "source": "r2"}

_FX_CACHE_KEY_TEMPLATE = "_fx:{base}:{target}"
_FX_CACHE_TTL_SECONDS = 24 * 60 * 60
_FX_API = "https://open.er-api.com/v6/latest/{base}"

def _fx_supported(currency: str) -> bool:
    return currency.isalpha() and 2 <= len(currency) <= 5

@router.get("/exchange-rate")
async def exchange_rate(base: str = "USD", target: str = "PHP",
                        user=Depends(require_user)) -> Dict[str, Any]:

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
        pass

    return {
        "base": base,
        "target": target,
        "rate": float(rate),
        "fetched_at": datetime.utcfromtimestamp(now).isoformat() + "Z",
        "cached": False,
    }
