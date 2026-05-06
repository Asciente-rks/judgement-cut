
from ...db import database, price_history

def _normalize_deal_id(deal_id: str) -> str:

    if not deal_id:
        return deal_id
    return deal_id.replace("=", "%3D")

async def get_price_history_for_deal(deal_id: str, limit: int = 50):
    deal_id = _normalize_deal_id(deal_id)
    query = (
        price_history.select()
        .where(price_history.c.deal_id == deal_id)
        .order_by(price_history.c.recorded_at.desc())
        .limit(limit)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]

async def insert_price_record(deal_id: str, price: float):

    from datetime import datetime
    q = price_history.insert().values(
        deal_id=deal_id,
        price=price,
        recorded_at=datetime.utcnow(),
    )
    await database.execute(q)
