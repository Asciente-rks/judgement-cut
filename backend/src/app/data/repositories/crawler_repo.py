from ...db import database, crawler_settings


async def upsert_crawler_setting(key: str, value: str):
    # Try update
    q = crawler_settings.update().where(crawler_settings.c.key == key).values(value=value)
    res = await database.execute(q)
    # databases.execute returns primary key or None depending on driver; do a select to ensure existence
    sel = crawler_settings.select().where(crawler_settings.c.key == key)
    row = await database.fetch_one(sel)
    if not row:
        await database.execute(crawler_settings.insert().values(key=key, value=value))
    return {"key": key, "value": value}


async def get_crawler_setting(key: str):
    q = crawler_settings.select().where(crawler_settings.c.key == key)
    row = await database.fetch_one(q)
    return row["value"] if row else None
