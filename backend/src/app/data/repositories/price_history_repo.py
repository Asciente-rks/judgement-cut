from ...db import database, price_history


async def get_price_history_for_deal(deal_id: str, limit: int = 50):
    query = price_history.select().where(price_history.c.deal_id == deal_id).order_by(price_history.c.recorded_at.desc()).limit(limit)
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]


async def insert_price_record(deal_id: str, price: float):
    q = price_history.insert().values(deal_id=deal_id, price=price)
    await database.execute(q)
