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
          "initial": 119900,        # cents-equivalent (₱1199.00)
          "final": 8995,            # ₱89.95
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
"""
from dataclasses import dataclass
from typing import Optional

import httpx


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
      - The Steam API call fails (timeout, non-200, malformed JSON)
    The caller can then fall back to USD->local FX conversion.
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
    try:
        async with httpx.AsyncClient(timeout=8, headers=_HEADERS) as client:
            resp = await client.get(_STEAM_APPDETAILS, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return None

    entry = payload.get(str(app_id)) or {}
    if not entry.get("success"):
        return None

    overview = (entry.get("data") or {}).get("price_overview")
    if not overview:
        return None

    try:
        # Steam returns prices as integers in 1/100 units of the currency
        # (e.g. 8995 means 89.95 PHP). Some currencies use 1/1000 but
        # Steam normalizes to two decimal places for PHP.
        initial = float(overview["initial"]) / 100.0
        final = float(overview["final"]) / 100.0
    except (KeyError, TypeError, ValueError):
        return None

    return RegionalPrice(
        currency=overview.get("currency", country_code),
        initial=initial,
        final=final,
        discount_percent=int(overview.get("discount_percent") or 0),
    )
