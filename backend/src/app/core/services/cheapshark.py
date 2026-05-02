import os
from typing import Dict, Any
import httpx
from ..config import CHEAPSHARK_BASE


async def fetch_deals(params: Dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{CHEAPSHARK_BASE}/deals", params=params)
        resp.raise_for_status()
        return resp.json()
