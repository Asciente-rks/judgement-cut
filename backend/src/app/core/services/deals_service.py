from typing import Any, Dict, List
from ..core.services.cheapshark import fetch_deals as live_fetch
from ..data.repositories.deals_repo import get_featured_deals
from ..data.repositories.platforms_repo import get_enabled_platforms
from ..data.repositories.price_history_repo import get_price_history_for_deal, insert_price_record

# CheapShark store IDs for the platforms seeded in the DB
CHEAPSHARK_STORE_ID_MAP = {
    "1": "Steam",
    "7": "GOG",
    "11": "Humble",
    "25": "Epic",
}


async def fetch_featured(limit: int = 20) -> List[Dict[str, Any]]:
    return await get_featured_deals(limit=limit)


async def search_game_live(title: str, pageSize: int = 60) -> List[Dict[str, Any]]:
    params = {"title": title, "pageSize": pageSize}
    data = await live_fetch(params)
    # filter out disabled platforms
    enabled = set(await get_enabled_platforms())
    def is_enabled(deal: Dict[str, Any]) -> bool:
        store_id = str(deal.get("storeID") or "")
        store_name = CHEAPSHARK_STORE_ID_MAP.get(store_id)
        return store_id in enabled or store_name in enabled

    filtered = [d for d in data if is_enabled(d)]

    # record prices into history asynchronously (fire-and-forget not implemented here)
    for d in filtered:
        try:
            await insert_price_record(d.get("dealID"), float(d.get("price", 0)))
        except Exception:
            pass

    return filtered


async def get_price_history(deal_id: str, limit: int = 50):
    return await get_price_history_for_deal(deal_id, limit=limit)
