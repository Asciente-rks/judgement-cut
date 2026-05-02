from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from ..clients.cheapshark import fetch_deals

router = APIRouter()


@router.get("/deals")
async def get_deals(storeID: Optional[str] = None, title: Optional[str] = None, pageSize: int = 60):
    params = {}
    if storeID:
        params["storeID"] = storeID
    if title:
        params["title"] = title
    params["pageSize"] = pageSize

    try:
        data = await fetch_deals(params)
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
