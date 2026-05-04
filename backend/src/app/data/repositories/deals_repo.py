"""featured_deals repository.

Inserts go through `upsert_featured_deal` which uses MySQL-style
INSERT ... ON DUPLICATE KEY UPDATE (relies on the unique index on
deal_id added in db.py migrations). This stops the spider's daily
re-ingestion from filling the table with duplicates.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.mysql import insert as mysql_insert

from ...db import database, featured_deals


# Whitelist of columns we accept on insert. Anything not in this set is
# silently dropped so that callers (the spider, /internal/ingest, admin
# tools) can't accidentally write into columns that don't belong.
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

# Columns we DO want refreshed on each spider re-ingest. Excludes id and
# deal_id (PK / dedup key) and synced_at (set automatically below).
# `regional_price_at`, `price_php`, `normal_price_php` aren't in here -
# they're populated by a separate code path (Steam regional API) and
# shouldn't be wiped just because the spider doesn't send them.
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
        .order_by(featured_deals.c.deal_rating.desc())
        .limit(limit)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]


async def get_deal_by_id(deal_id: str):
    """Return the row for this deal_id, or None.

    With the UNIQUE INDEX in place, deal_id is a primary lookup key
    (only one row per deal_id ever exists).
    """
    query = featured_deals.select().where(featured_deals.c.deal_id == deal_id)
    row = await database.fetch_one(query)
    return dict(row) if row else None


async def insert_featured_deal(deal: dict):
    """Upsert by deal_id.

    Existing rows have their `_UPSERT_REFRESH_COLUMNS` overwritten and
    `synced_at` updated. The native regional-pricing columns are left
    alone (they're maintained by the Steam enrichment path).
    """
    cleaned = {k: v for k, v in deal.items() if k in _ALLOWED_COLUMNS}
    if not cleaned or not cleaned.get("deal_id"):
        return

    cleaned["synced_at"] = datetime.utcnow()

    stmt = mysql_insert(featured_deals).values(**cleaned)
    update_payload = {
        c: stmt.inserted[c]
        for c in cleaned
        if c in _UPSERT_REFRESH_COLUMNS
    }
    update_payload["synced_at"] = stmt.inserted["synced_at"]
    stmt = stmt.on_duplicate_key_update(**update_payload)
    await database.execute(stmt)


async def update_thumbnail_for_deal(deal_id: str, thumbnail_url: str) -> int:
    """Set thumbnail_url for the row sharing this deal_id. Returns row count."""
    query = (
        featured_deals.update()
        .where(featured_deals.c.deal_id == deal_id)
        .values(thumbnail_url=thumbnail_url)
    )
    return await database.execute(query)


async def update_regional_pricing(deal_id: str, *,
                                  price_php: Optional[float],
                                  normal_price_php: Optional[float]) -> int:
    """Cache native regional pricing on a deal."""
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
