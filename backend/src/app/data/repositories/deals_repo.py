"""featured_deals repository.

Inserts go through `insert_featured_deal` which uses MySQL-style
INSERT ... ON DUPLICATE KEY UPDATE (relies on the unique index on
deal_id added in db.py migrations). This stops the spider's daily
re-ingestion from filling the table with duplicates.

Active vs stale deals:
  Each upsert stamps `last_seen_at = NOW()` and `is_active = 1`. At end
  of crawl, /internal/ingest/finalize calls `mark_stale_deals_inactive`
  which flips is_active=0 on any row whose last_seen_at is older than
  the run's start time. /v1/deals/featured then filters to is_active=1
  so the dashboard's "live deals" count reflects the latest crawl, not
  every deal ever seen.
"""
from datetime import datetime, timezone
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
    """Return active deals ordered by deal_rating desc.

    `is_active = 1` filter excludes stale deals from previous runs that
    are no longer on sale. Without this filter the table grows unbounded
    (no expiration logic) and the dashboard's "live deals" count drifts
    upward forever.
    """
    query = (
        featured_deals.select()
        .where(featured_deals.c.is_active == True)  # noqa: E712 (SQLAlchemy)
        .order_by(featured_deals.c.deal_rating.desc())
        .limit(limit)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]


def _normalize_deal_id(deal_id: str) -> str:
    """Re-encode `=` to `%3D`.

    CheapShark deal_ids are stored with the URL-encoded `%3D` suffix,
    but Lambda Function URL infrastructure decodes the path twice
    (once at the AWS HTTP frontend, once in Starlette) before it
    reaches us, leaving `=`. Normalize to match the stored form.
    """
    if not deal_id:
        return deal_id
    return deal_id.replace("=", "%3D")


async def get_deal_by_id(deal_id: str):
    """Return the row for this deal_id, or None.

    With the UNIQUE INDEX in place, deal_id is a primary lookup key
    (only one row per deal_id ever exists).
    """
    deal_id = _normalize_deal_id(deal_id)
    query = featured_deals.select().where(featured_deals.c.deal_id == deal_id)
    row = await database.fetch_one(query)
    return dict(row) if row else None


async def insert_featured_deal(deal: dict):
    """Upsert by deal_id.

    Existing rows have their `_UPSERT_REFRESH_COLUMNS` overwritten and
    `synced_at` / `last_seen_at` / `is_active` updated. The native
    regional-pricing columns are left alone (they're maintained by the
    Steam enrichment path).

    Stamping last_seen_at and flipping is_active=1 here is what lets
    the finalize step at end of crawl distinguish "seen this run" from
    "stale, came off sale, mark inactive".
    """
    cleaned = {k: v for k, v in deal.items() if k in _ALLOWED_COLUMNS}
    if not cleaned or not cleaned.get("deal_id"):
        return

    now = datetime.utcnow()
    cleaned["synced_at"] = now

    # last_seen_at and is_active aren't user-provided - they're owned
    # by this upsert path. Set them outside the _ALLOWED_COLUMNS check
    # so callers can't override them.
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


async def mark_stale_deals_inactive(run_started_at_epoch: int) -> int:
    """Set is_active=0 for any deal not seen in the latest crawl.

    Called by /internal/ingest/finalize at end of run. The threshold is
    the spider's run start time (epoch seconds). Any row whose
    last_seen_at is NULL (never seen, including pre-migration rows) or
    older than the threshold is considered stale.

    Returns the number of rows marked inactive so the caller can log /
    surface that on the admin monitor.
    """
    threshold = datetime.utcfromtimestamp(int(run_started_at_epoch))
    query = (
        featured_deals.update()
        .where(
            (featured_deals.c.is_active == True)  # noqa: E712
            & (
                (featured_deals.c.last_seen_at == None)  # noqa: E711
                | (featured_deals.c.last_seen_at < threshold)
            )
        )
        .values(is_active=False)
    )
    return await database.execute(query)
