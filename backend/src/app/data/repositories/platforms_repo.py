from ...db import database, platforms

async def get_enabled_platforms() -> list:
    query = platforms.select().where(platforms.c.is_enabled == True)
    rows = await database.fetch_all(query)
    return [r["name"] for r in rows]

async def set_platform_enabled(name: str, enabled: bool):
    query = platforms.update().where(platforms.c.name == name).values(is_enabled=enabled)
    await database.execute(query)
