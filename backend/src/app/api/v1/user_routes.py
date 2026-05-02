from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from ...core.services.deals_service import fetch_featured, search_game_live, get_price_history
from ...api.dependencies import get_current_user

router = APIRouter()


@router.get("/deals/featured")
async def featured(limit: int = 20, user=Depends(get_current_user)):
    return await fetch_featured(limit=limit)


@router.get("/deals/search")
async def search(title: str, pageSize: int = 60, user=Depends(get_current_user)):
    return await search_game_live(title=title, pageSize=pageSize)


@router.get("/deals/{deal_id}/history")
async def history(deal_id: str, limit: int = 50, user=Depends(get_current_user)):
    return await get_price_history(deal_id, limit=limit)
