"""price_history repository.

Note on deal_id encoding: CheapShark deal IDs are pre-URL-encoded
strings ending in '%3D' (base64 padding). When the frontend sends them
through Lambda Function URLs the path gets decoded TWICE - once by AWS
Lambda's HTTP frontend, once by Starlette - so by the time it reaches
the handler, '%3D' has become '='. We normalize back before lookup so
the stored '%3D' form matches.
"""
from ...db import database, price_history


def _normalize_deal_id(deal_id: str) -> str:
    """Re-encode `=` to `%3D` to undo double URL-decoding by Lambda.

    CheapShark IDs are stored with the encoded form (`%3D`). Other
    deal IDs (Epic etc.) don't contain '=' so this is a no-op for them.
    """
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
    # Stored as-given (CheapShark already provides the URL-encoded form).
    q = price_history.insert().values(deal_id=deal_id, price=price)
    await database.execute(q)
