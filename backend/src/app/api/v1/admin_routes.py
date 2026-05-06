
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ...api.dependencies import require_admin
from ...api.internal import LAST_INGEST_AT_KEY, LAST_INGEST_COUNT_KEY
from ...db import database, featured_deals, platforms, users
from ...data.repositories.crawler_repo import (
    get_crawler_setting,
    upsert_crawler_setting,
)
from ...data.repositories.platforms_repo import set_platform_enabled
from ...data.storage import (
    delete_file_from_r2,
    r2_is_configured,
    upload_file_to_r2,
)

router = APIRouter()

@router.get("/platforms")
async def list_platforms(_=Depends(require_admin)):

    rows = await database.fetch_all(platforms.select().order_by(platforms.c.name))
    return [
        {"id": r["id"], "name": r["name"], "is_enabled": bool(r["is_enabled"])}
        for r in rows
    ]

@router.post("/platforms/{platform_name}/toggle")
async def toggle_platform(platform_name: str, enabled: bool,
                          _=Depends(require_admin)):
    await set_platform_enabled(platform_name, enabled)
    return {"platform": platform_name, "is_enabled": enabled}

@router.post("/crawler/settings")
async def set_crawler_setting(key: str, value: str,
                              _=Depends(require_admin)):
    return await upsert_crawler_setting(key, value)

@router.get("/monitor/scraper")
async def monitor_scraper(_=Depends(require_admin)):

    from datetime import datetime, timezone
    import httpx
    from sqlalchemy import func, select

    status: dict = {}

    try:
        r = httpx.get(
            "https://www.cheapshark.com/api/1.0/deals",
            params={"storeID": "1", "pageSize": 1},
            timeout=5,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JudgementCut/1.0; "
                    "+https://github.com/Asciente-rks/judgement-cut)"
                ),
                "Accept": "application/json",
            },
        )
        status["cheapshark_status"] = r.status_code
        status["cheapshark_ok"] = r.status_code == 200
    except Exception as exc:
        status["cheapshark_error"] = str(exc)
        status["cheapshark_ok"] = False

    last_ts_raw = await get_crawler_setting(LAST_INGEST_AT_KEY)
    last_count_raw = await get_crawler_setting(LAST_INGEST_COUNT_KEY)
    if last_ts_raw:
        try:
            ts = int(last_ts_raw)
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            now = datetime.now(tz=timezone.utc).timestamp()
            status["last_ingest_at"] = iso
            status["last_ingest_seconds_ago"] = int(now - ts)
        except (ValueError, TypeError):
            status["last_ingest_at"] = None
    else:
        status["last_ingest_at"] = None

    if last_count_raw:
        try:
            status["last_ingest_count"] = int(last_count_raw)
        except (ValueError, TypeError):
            status["last_ingest_count"] = None
    else:
        status["last_ingest_count"] = None

    try:
        row = await database.fetch_one(
            select(func.count()).select_from(featured_deals)
        )
        status["featured_deals_count"] = int(row[0]) if row else 0
    except Exception as exc:
        status["featured_deals_error"] = str(exc)
        status["featured_deals_count"] = None

    status["zyte"] = "not-configured"
    status["r2_configured"] = r2_is_configured()
    status["scraper_secret_set"] = bool(_scraper_secret_present())

    return status

def _scraper_secret_present() -> bool:

    from ...core import config as _cfg
    return bool(getattr(_cfg, "SCRAPER_SECRET", None))

@router.get("/users")
async def list_users(caller=Depends(require_admin)):

    rows = await database.fetch_all(users.select().order_by(users.c.username))
    return [
        {"id": r["id"], "username": r["username"], "is_admin": bool(r["is_admin"])}
        for r in rows
    ]

@router.post("/users/{username}/admin")
async def set_user_admin(username: str, enabled: bool,
                         caller=Depends(require_admin)):

    if username == caller["username"] and not enabled:
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own admin privileges",
        )
    row = await database.fetch_one(
        users.select().where(users.c.username == username)
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    await database.execute(
        users.update()
        .where(users.c.username == username)
        .values(is_admin=enabled)
    )
    return {"username": username, "is_admin": enabled}

@router.post("/assets/upload")
async def upload_asset(file: UploadFile = File(...),
                       _=Depends(require_admin)):
    if not r2_is_configured():
        raise HTTPException(status_code=503,
                            detail="R2 storage is not configured")
    data = await file.read()
    key = file.filename
    resp = upload_file_to_r2(bucket=None, key=key, data=data,
                             content_type=file.content_type)
    return {"key": key, "result": resp}

@router.delete("/assets/{key}")
async def delete_asset(key: str, _=Depends(require_admin)):
    if not r2_is_configured():
        raise HTTPException(status_code=503,
                            detail="R2 storage is not configured")
    ok = delete_file_from_r2(bucket=None, key=key)
    return {"key": key, "deleted": ok}
