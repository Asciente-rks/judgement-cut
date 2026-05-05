"""Steam storefront regional pricing.

CheapShark hands us USD prices that don't reflect Steam's actual
country-specific pricing strategy. For a Steam deal we instead query
the official storefront with `cc=PH` to get the native PHP price.

Endpoint: store.steampowered.com/api/appdetails?appids=X&cc=PH
          &filters=price_overview

Sample response payload:
  {
    "1238820": {
      "success": true,
      "data": {
        "price_overview": {
          "currency": "PHP",
          "initial": 119900,        # cents-equivalent (PHP1199.00)
          "final": 8995,            # PHP89.95
          "discount_percent": 92,
          ...
        }
      }
    }
  }

Free games typically come back with success=true but price_overview
absent. Region-locked games come back with success=false. Both are
treated as 'no native price available', and the caller falls back to
USD * fx_rate.

Reliability: We retry up to 3 times on network/timeout/5xx errors with
exponential backoff (0.5s, 1s, 2s). Without retries, a single transient
failure leaves the deal with `price_php = NULL` and the frontend silently
falls back to a USD-converted price that doesn't match what Steam
actually shows in PH (the bug the user reported with NBA 2K26).
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


_STEAM_APPDETAILS = "https://store.steampowered.com/api/appdetails"
# Mozilla UA matches the spider; some Steam endpoints are stricter
# from cloud IPs without a browser-like UA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JudgementCut/1.0; "
        "+https://github.com/Asciente-rks/judgement-cut)"
    ),
    "Accept": "application/json",
}

# Per-attempt timeout. Steam's CDN occasionally takes 5+ seconds, so 10s
# is generous but bounded. Total worst-case across retries: ~13s of API
# time + ~3.5s of backoff sleep = ~17s, well within the Lambda 30s budget.
_REQUEST_TIMEOUT_SECONDS = 10

# Exponential backoff between retries. Network blips usually clear in
# under a second; longer Steam slowdowns benefit from the larger jumps.
_RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)


@dataclass(frozen=True)
class RegionalPrice:
    currency: str          # ISO 4217 e.g. "PHP"
    initial: float         # original (pre-discount) in major units
    final: float           # discounted / sale price in major units
    discount_percent: int  # Steam's reported discount, 0..100


async def fetch_steam_regional_price(
    app_id: str,
    country_code: str = "PH",
) -> Optional[RegionalPrice]:
    """Fetch native pricing for a Steam app in the given country.

    Returns None when:
      - The app doesn't exist or is region-locked (success=false)
      - The app is free and Steam doesn't return a price_overview
      - All retries to the Steam API fail (timeout, 5xx, malformed JSON)

    Retries on transient network/server errors. Does NOT retry on
    "no data" outcomes (success=false, missing price_overview) -
    those are stable answers from Steam, retrying won't change them.

    The caller can then fall back to USD->local FX conversion when this
    returns None.
    """
    if not app_id:
        return None

    params = {
        "appids": str(app_id),
        "cc": country_code,
        "filters": "price_overview",
        # Specifying language doesn't change pricing but makes the
        # response shape predictable.
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

                # Retry on 5xx (Steam server hiccup). Don't retry on 4xx
                # (those are stable client errors - bad app_id, etc.).
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
                break  # success

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
            # Non-retryable: 4xx, JSON decode error, etc. Log and bail.
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
        # Stable "no" from Steam (region-locked, app removed, etc.).
        # Don't log at WARN level - this is normal for ~5-10% of deals.
        logger.debug(
            "Steam appdetails success=false for app_id=%s cc=%s",
            app_id, country_code,
        )
        return None

    overview = (entry.get("data") or {}).get("price_overview")
    if not overview:
        # Free game or no pricing data. Also normal.
        logger.debug(
            "Steam appdetails no price_overview for app_id=%s cc=%s",
            app_id, country_code,
        )
        return None

    try:
        # Steam returns prices as integers in 1/100 units of the currency
        # (e.g. 8995 means 89.95 PHP). Some currencies use 1/1000 but
        # Steam normalizes to two decimal places for PHP.
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
    """Look up a Steam app_id by game title.

    Used as a fallback when CheapShark didn't include `steamAppID` for a
    Steam-store deal (a few percent of CheapShark's Steam catalog).
    Without this, the deal stays with price_php=NULL and the frontend
    falls back to USD * FX even though Steam HAS a native PH price for
    that game.

    Confidence check: only return the app_id if the matched name has a
    substring relationship with the search title. Catches obvious wrong
    matches like searching "Rust" and getting "Rust - Voice Props Pack"
    - Steam orders by relevance so the top result is usually right, but
    the similar-name DLC trap is real.

    Returns None when:
      - title is empty
      - Steam search returns no results
      - The top result isn't an "app" (could be DLC bundle, sub, etc.)
      - The top result's name doesn't substring-match the search title
      - The Steam API call fails
    """
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
        # Could be "sub" (sub-product / package) or "bundle". Those don't
        # have prices in the appdetails API the same way, so skip.
        return None

    found_name = (top.get("name") or "").strip().lower()
    sought_name = title.strip().lower()
    if not found_name:
        return None

    # Substring match in either direction. We don't require exact match
    # because CheapShark titles often have edition suffixes ("Game of the
    # Year Edition") while Steam shows the base name.
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
