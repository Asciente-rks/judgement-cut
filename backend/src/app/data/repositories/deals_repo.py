
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...db import database, featured_deals

_ALLOWED_COLUMNS = {
    "deal_id",
    "title",
    "store_id",
    "price",
    "normal_price",
    "deal_rating",
    "thumbnail_url",
    "steam_app_id",
    "price_php",
    "normal_price_php",
    "regional_price_at",
}

_UPSERT_REFRESH_COLUMNS = {
    "title",
    "store_id",
    "price",
    "normal_price",
    "deal_rating",
    "thumbnail_url",
    "steam_app_id",
}

async def get_featured_deals(limit: int = 20):

    query = (
        featured_deals.select()
        .where(featured_deals.c.is_active == True)
        .order_by(featured_deals.c.deal_rating.desc())
        .limit(limit)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]

def _normalize_deal_id(deal_id: str) -> str:

    if not deal_id:
        return deal_id
    return deal_id.replace("=", "%3D")

async def get_deal_by_id(deal_id: str):

    deal_id = _normalize_deal_id(deal_id)
    query = featured_deals.select().where(featured_deals.c.deal_id == deal_id)
    row = await database.fetch_one(query)
    return dict(row) if row else None

async def insert_featured_deal(deal: dict):

    cleaned = {k: v for k, v in deal.items() if k in _ALLOWED_COLUMNS}
    if not cleaned or not cleaned.get("deal_id"):
        return

    now = datetime.utcnow()
    cleaned["synced_at"] = now

    full_values = {**cleaned, "last_seen_at": now, "is_active": True}

    stmt = mysql_insert(featured_deals).values(**full_values)
    update_payload = {
        c: stmt.inserted[c]
        for c in cleaned
        if c in _UPSERT_REFRESH_COLUMNS
    }
    update_payload["synced_at"] = stmt.inserted["synced_at"]
    update_payload["last_seen_at"] = stmt.inserted["last_seen_at"]
    update_payload["is_active"] = stmt.inserted["is_active"]
    stmt = stmt.on_duplicate_key_update(**update_payload)
    await database.execute(stmt)

async def update_thumbnail_for_deal(deal_id: str, thumbnail_url: str) -> int:

    query = (
        featured_deals.update()
        .where(featured_deals.c.deal_id == deal_id)
        .values(thumbnail_url=thumbnail_url)
    )
    return await database.execute(query)

async def update_regional_pricing(deal_id: str, *,
                                  price_php: Optional[float],
                                  normal_price_php: Optional[float]) -> int:

    query = (
        featured_deals.update()
        .where(featured_deals.c.deal_id == deal_id)
        .values(
            price_php=price_php,
            normal_price_php=normal_price_php,
            regional_price_at=datetime.utcnow(),
        )
    )
    return await database.execute(query)

async def update_steam_app_id(deal_id: str, steam_app_id: str) -> int:

    query = (
        featured_deals.update()
        .where(featured_deals.c.deal_id == deal_id)
        .values(steam_app_id=steam_app_id)
    )
    return await database.execute(query)

async def mark_stale_deals_inactive(run_started_at_epoch: int) -> int:

    threshold = datetime.utcfromtimestamp(int(run_started_at_epoch))
    query = (
        featured_deals.update()
        .where(
            (featured_deals.c.is_active == True)
            & (
                (featured_deals.c.last_seen_at == None)
                | (featured_deals.c.last_seen_at < threshold)
            )
        )
        .values(is_active=False)
    )
    return await database.execute(query)

async def delete_stale_deals() -> int:

    query = featured_deals.delete().where(
        featured_deals.c.is_active == False
    )
    return await database.execute(query)

async def get_active_deals_needing_enrichment(
    limit: int = 50,
) -> List[Dict[str, Any]]:

    query = (
        featured_deals.select()
        .where(
            (featured_deals.c.is_active == True)
            & (featured_deals.c.store_id == "1")
            & (featured_deals.c.price_php == None)
        )
        .limit(limit)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]
