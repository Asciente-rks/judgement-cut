"""CheapShark client used from inside Lambda.

CheapShark accepts the bare httpx default UA from most regions but
returns 400 from ap-southeast-1 unless we identify ourselves with a
browser-like UA. We also send Accept: application/json explicitly so
nothing in transit decides to give us HTML.
"""
from typing import Any, Dict

import httpx

from ..config import CHEAPSHARK_BASE


# Mozilla/5.0 prefix is the universal "treat me like a browser" hint.
# We append our own identifier so server logs can still tell who we are.
_USER_AGENT = (
    "Mozilla/5.0 (compatible; JudgementCut/1.0; "
    "+https://github.com/Asciente-rks/judgement-cut)"
)
_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json",
}


async def fetch_deals(params: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=10, headers=_DEFAULT_HEADERS) as client:
        resp = await client.get(f"{CHEAPSHARK_BASE}/deals", params=params)
        resp.raise_for_status()
        return resp.json()
