from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from ...api.dependencies import get_current_user
from ...db import database, platforms, crawler_settings
from ...data.storage import upload_file_to_r2, delete_file_from_r2
from ...data.repositories.platforms_repo import set_platform_enabled

router = APIRouter()


@router.post("/platforms/{platform_name}/toggle")
async def toggle_platform(platform_name: str, enabled: bool, user=Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requires admin privileges")

    await set_platform_enabled(platform_name, enabled)
    return {"platform": platform_name, "is_enabled": enabled}


@router.post("/crawler/settings")
async def set_crawler_setting(key: str, value: str, user=Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requires admin privileges")
    from ...data.repositories.crawler_repo import upsert_crawler_setting

    res = await upsert_crawler_setting(key, value)
    return res


@router.post("/assets/upload")
async def upload_asset(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requires admin privileges")
    data = await file.read()
    key = file.filename
    resp = upload_file_to_r2(bucket=None, key=key, data=data)
    return {"key": key, "result": resp}


@router.delete("/assets/{key}")
async def delete_asset(key: str, user=Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Requires admin privileges")
    ok = delete_file_from_r2(bucket=None, key=key)
    return {"key": key, "deleted": ok}


@router.get("/monitor/scraper")
async def monitor_scraper(user=Depends(get_current_user)):
    # Check CheapShark reachability
    import httpx
    try:
        r = httpx.get("https://www.cheapshark.com/api/1.0/deals", params={"pageSize": 1}, timeout=5)
        status = {"cheapshark_status": r.status_code}
    except Exception as e:
        status = {"cheapshark_error": str(e)}
    # Zyte integration requires API key — left as placeholder
    status["zyte"] = "not-configured"
    return status
