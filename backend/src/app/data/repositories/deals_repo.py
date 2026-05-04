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
    """Return the most recently synced row for this deal_id, or None."""
    query = (
        featured_deals.select()
        .where(featured_deals.c.deal_id == deal_id)
        .order_by(featured_deals.c.synced_at.desc())
        .limit(1)
    )
    row = await database.fetch_one(query)
    return dict(row) if row else None


async def insert_featured_deal(deal: dict):
    cleaned = {k: v for k, v in deal.items() if k in _ALLOWED_COLUMNS}
    if not cleaned:
        return
    await database.execute(featured_deals.insert().values(**cleaned))


async def update_thumbnail_for_deal(deal_id: str, thumbnail_url: str) -> int:
    """Set thumbnail_url for every row sharing this deal_id. Returns row count."""
    query = (
        featured_deals.update()
        .where(featured_deals.c.deal_id == deal_id)
        .values(thumbnail_url=thumbnail_url)
    )
    return await database.execute(query)
