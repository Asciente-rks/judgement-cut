
from typing import Any, Dict

import httpx

from ..config import CHEAPSHARK_BASE

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
