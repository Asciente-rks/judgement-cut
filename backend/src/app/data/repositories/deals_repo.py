from ...db import database, featured_deals


async def get_featured_deals(limit: int = 20):
    query = featured_deals.select().order_by(featured_deals.c.deal_rating.desc()).limit(limit)
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]


async def insert_featured_deal(deal: dict):
    # upsert by deal_id (simple implementation)
    q = featured_deals.insert().values(**deal)
    await database.execute(q)
