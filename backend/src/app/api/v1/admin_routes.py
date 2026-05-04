"""Admin-only endpoints (/v1/admin/...).

Every route here is gated by `require_admin` so the routing layer
itself enforces RBAC; we don't have the old ad-hoc `if not is_admin`
pattern in each handler.
"""
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ...api.dependencies import require_admin
from ...db import database, platforms, users
from ...data.repositories.crawler_repo import upsert_crawler_setting
from ...data.repositories.platforms_repo import set_platform_enabled
from ...data.storage import (
    delete_file_from_r2,
    r2_is_configured,
    upload_file_to_r2,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Platform toggles
# ---------------------------------------------------------------------------


@router.get("/platforms")
async def list_platforms(_=Depends(require_admin)):
    """All platforms with their current enabled flag."""
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


# ---------------------------------------------------------------------------
# Crawler / scraper settings
# ---------------------------------------------------------------------------


@router.post("/crawler/settings")
async def set_crawler_setting(key: str, value: str,
                              _=Depends(require_admin)):
    return await upsert_crawler_setting(key, value)


@router.get("/monitor/scraper")
async def monitor_scraper(_=Depends(require_admin)):
    """Quick health check on the upstream we depend on (CheapShark)."""
    import httpx
    try:
        r = httpx.get(
            "https://www.cheapshark.com/api/1.0/deals",
            params={"pageSize": 1},
            timeout=5,
        )
        status = {"cheapshark_status": r.status_code}
    except Exception as exc:
        status = {"cheapshark_error": str(exc)}
    # Zyte integration requires API key — left as placeholder.
    status["zyte"] = "not-configured"
    status["r2_configured"] = r2_is_configured()
    return status


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(caller=Depends(require_admin)):
    """List every user with their admin flag. Used by the admin panel."""
    rows = await database.fetch_all(users.select().order_by(users.c.username))
    return [
        {"id": r["id"], "username": r["username"], "is_admin": bool(r["is_admin"])}
        for r in rows
    ]


@router.post("/users/{username}/admin")
async def set_user_admin(username: str, enabled: bool,
                         caller=Depends(require_admin)):
    """Promote / demote a user. Self-demotion is blocked so an admin
    can't lock themselves out of the admin UI accidentally."""
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


# ---------------------------------------------------------------------------
# R2 asset upload (admin-only general file storage; not the deal thumbs)
# ---------------------------------------------------------------------------


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
