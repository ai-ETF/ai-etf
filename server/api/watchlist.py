"""
自选股 API 端点

提供自选股管理接口，user_id 从 JWT 中自动读取，不从请求体取。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from server.auth import get_current_user
from server.models.schemas import (
    WatchlistAddRequest,
    WatchlistRemoveRequest,
    WatchlistResponse,
    WatchlistActionResponse,
    WatchlistItem,
)
from server.services.watchlist_service import WatchlistService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.post("/add", response_model=WatchlistActionResponse)
async def add_watchlist(
    req: WatchlistAddRequest,
    current_user: str = Depends(get_current_user),
):
    """
    添加自选股（需 JWT 认证）

    user_id 从 JWT 中自动读取，无需在请求体中传入。
    """
    logger.info(f"添加自选股: user={current_user}, code={req.fund_code}")
    svc = WatchlistService()

    result = svc.add(
        user_id=current_user,
        fund_code=req.fund_code,
        fund_name=req.fund_name,
    )

    return WatchlistActionResponse(
        success=result["success"],
        message=result["message"],
        item=WatchlistItem(**result["item"]) if result.get("item") else None,
    )


@router.delete("/remove", response_model=WatchlistActionResponse)
async def remove_watchlist(
    req: WatchlistRemoveRequest,
    current_user: str = Depends(get_current_user),
):
    """
    移除自选股（需 JWT 认证）

    user_id 从 JWT 中自动读取，无需在请求体中传入。
    """
    logger.info(f"移除自选股: user={current_user}, code={req.fund_code}")
    svc = WatchlistService()

    result = svc.remove(user_id=current_user, fund_code=req.fund_code)

    return WatchlistActionResponse(
        success=result["success"],
        message=result["message"],
        item=None,
    )


@router.get("/list", response_model=WatchlistResponse)
async def list_watchlist(
    include_quote: bool = Query(True, description="是否包含实时行情"),
    current_user: str = Depends(get_current_user),
):
    """
    查询自选股列表（需 JWT 认证）

    user_id 从 JWT 中自动读取，无需在 URL 中传入。
    """
    logger.info(f"查询自选股列表: user={current_user}, include_quote={include_quote}")
    svc = WatchlistService()

    result = svc.list(user_id=current_user, include_quote=include_quote)

    items = [WatchlistItem(**item) for item in result["items"]]

    return WatchlistResponse(total=result["total"], items=items)


@router.delete("/clear")
async def clear_watchlist(current_user: str = Depends(get_current_user)):
    """
    清空自选股列表（需 JWT 认证）

    user_id 从 JWT 中自动读取，无需在 URL 中传入。
    """
    logger.info(f"清空自选股: user={current_user}")
    svc = WatchlistService()

    result = svc.clear(user_id=current_user)

    return result


@router.get("/health")
async def health_check():
    """健康检查（公开）"""
    return {"status": "ok", "service": "watchlist"}