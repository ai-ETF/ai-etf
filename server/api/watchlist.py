"""
自选股 API 端点

提供自选股管理接口：
1. 添加自选股
2. 移除自选股
3. 查询自选股列表
4. 清空自选股
"""

from fastapi import APIRouter, HTTPException, Query
from server.models.schemas import (
    WatchlistAddRequest,
    WatchlistRemoveRequest,
    WatchlistResponse,
    WatchlistActionResponse,
    WatchlistItem,
)
from server.services.watchlist_service import WatchlistService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/add", response_model=WatchlistActionResponse)
async def add_watchlist(req: WatchlistAddRequest):
    """
    添加自选股

    请求体:
        user_id: 用户ID
        fund_code: 基金代码（如 512890）
        fund_name: 基金名称（可选，系统自动获取）

    返回:
        WatchlistActionResponse
    """
    logger.info(f"添加自选股: user={req.user_id}, code={req.fund_code}")
    svc = WatchlistService()

    result = svc.add(
        user_id=req.user_id,
        fund_code=req.fund_code,
        fund_name=req.fund_name
    )

    return WatchlistActionResponse(
        success=result["success"],
        message=result["message"],
        item=WatchlistItem(**result["item"]) if result.get("item") else None
    )


@router.delete("/remove", response_model=WatchlistActionResponse)
async def remove_watchlist(req: WatchlistRemoveRequest):
    """
    移除自选股

    请求体:
        user_id: 用户ID
        fund_code: 基金代码

    返回:
        WatchlistActionResponse
    """
    logger.info(f"移除自选股: user={req.user_id}, code={req.fund_code}")
    svc = WatchlistService()

    result = svc.remove(
        user_id=req.user_id,
        fund_code=req.fund_code
    )

    return WatchlistActionResponse(
        success=result["success"],
        message=result["message"],
        item=None
    )


@router.get("/list/{user_id}", response_model=WatchlistResponse)
async def list_watchlist(
    user_id: str,
    include_quote: bool = Query(True, description="是否包含实时行情")
):
    """
    查询自选股列表

    参数:
        user_id: 用户ID
        include_quote: 是否包含实时行情（默认 true）

    返回:
        WatchlistResponse: 包含自选股列表和实时行情
    """
    logger.info(f"查询自选股列表: user={user_id}, include_quote={include_quote}")
    svc = WatchlistService()

    result = svc.list(user_id=user_id, include_quote=include_quote)

    items = [WatchlistItem(**item) for item in result["items"]]

    return WatchlistResponse(
        total=result["total"],
        items=items
    )


@router.delete("/clear/{user_id}")
async def clear_watchlist(user_id: str):
    """
    清空自选股列表

    参数:
        user_id: 用户ID

    返回:
        {"success": bool, "message": str, "removed_count": int}
    """
    logger.info(f"清空自选股: user={user_id}")
    svc = WatchlistService()

    result = svc.clear(user_id=user_id)

    return result


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "watchlist"}