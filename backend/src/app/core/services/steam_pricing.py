
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JudgementCut/1.0; "
        "+https://github.com/Asciente-rks/judgement-cut)"
    ),
    "Accept": "application/json",
}

_REQUEST_TIMEOUT_SECONDS = 10

_RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

@dataclass(frozen=True)
class RegionalPrice:
    currency: str
    initial: float
    final: float
    discount_percent: int

async def fetch_steam_regional_price(
    app_id: str,
    country_code: str = "PH",
) -> Optional[RegionalPrice]:

    if not app_id:
        return None

    params = {
        "appids": str(app_id),
        "cc": country_code,
        "filters": "price_overview",

        "l": "en",
    }

    payload = None
    last_error = None
    for attempt, backoff in enumerate(_RETRY_BACKOFF_SECONDS):
        try:
            async with httpx.AsyncClient(
                timeout=_REQUEST_TIMEOUT_SECONDS,
                headers=_HEADERS,
            ) as client:
                resp = await client.get(_STEAM_APPDETAILS, params=params)

                if 500 <= resp.status_code < 600:
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning(
                        "Steam appdetails 5xx (attempt %d/%d) app_id=%s cc=%s status=%d",
                        attempt + 1, len(_RETRY_BACKOFF_SECONDS),
                        app_id, country_code, resp.status_code,
                    )
                    await asyncio.sleep(backoff)
                    continue

                resp.raise_for_status()
                payload = resp.json()
                break

        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            last_error = repr(e)
            logger.warning(
                "Steam appdetails network error (attempt %d/%d) app_id=%s cc=%s: %s",
                attempt + 1, len(_RETRY_BACKOFF_SECONDS),
                app_id, country_code, e,
            )
            await asyncio.sleep(backoff)
            continue

        except Exception as e:

            logger.warning(
                "Steam appdetails non-retryable error app_id=%s cc=%s: %s",
                app_id, country_code, e,
            )
            return None

    if payload is None:
        logger.error(
            "Steam appdetails exhausted retries for app_id=%s cc=%s last_error=%s",
            app_id, country_code, last_error,
        )
        return None

    entry = payload.get(str(app_id)) or {}
    if not entry.get("success"):

        logger.debug(
            "Steam appdetails success=false for app_id=%s cc=%s",
            app_id, country_code,
        )
        return None

    overview = (entry.get("data") or {}).get("price_overview")
    if not overview:

        logger.debug(
            "Steam appdetails no price_overview for app_id=%s cc=%s",
            app_id, country_code,
        )
        return None

    try:

        initial = float(overview["initial"]) / 100.0
        final = float(overview["final"]) / 100.0
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(
            "Steam appdetails malformed price_overview app_id=%s cc=%s err=%s",
            app_id, country_code, e,
        )
        return None

    return RegionalPrice(
        currency=overview.get("currency", country_code),
        initial=initial,
        final=final,
        discount_percent=int(overview.get("discount_percent") or 0),
    )

_STEAM_STORESEARCH = "https://store.steampowered.com/api/storesearch/"

async def search_steam_appid_by_title(title: str) -> Optional[str]:

    if not title:
        return None

    params = {
        "term": title,
        "cc": "PH",
        "l": "en",
    }
    try:
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(_STEAM_STORESEARCH, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:
        logger.warning("Steam storesearch failed for title=%r: %s", title, e)
        return None

    items = payload.get("items") or []
    if not items:
        logger.debug("Steam storesearch no results for title=%r", title)
        return None

    top = items[0]
    if top.get("type") != "app":

        return None

    found_name = (top.get("name") or "").strip().lower()
    sought_name = title.strip().lower()
    if not found_name:
        return None

    if found_name == sought_name:
        match_kind = "exact"
    elif sought_name in found_name or found_name in sought_name:
        match_kind = "substring"
    else:
        logger.debug(
            "Steam storesearch title-mismatch: sought=%r found=%r",
            title, found_name,
        )
        return None

    appid = top.get("id")
    if not appid or not str(appid).isdigit():
        return None

    logger.info(
        "Steam storesearch matched title=%r -> appid=%s (%s match: %r)",
        title, appid, match_kind, found_name,
    )
    return str(appid)
