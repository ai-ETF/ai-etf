"""
基金搜索 API（只搜支持目录内的场外基金）

提供：
- GET /api/market/search?keyword=   按代码或名称搜索

2026-10-26：`/filter`、`/categories`、`/category/{cat}` 随 30 秒行情缓存下线
——它们都基于全市场行情快照，没有数据源后无法维持契约。
"""

import logging

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import SearchResponse, SearchItem

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search_funds(
    keyword: str = Query(..., description="搜索关键词（基金代码或名称）"),
    top_n: int = Query(10, ge=1, le=50),
):
    """搜索基金。

    只返回支持目录（`fund_catalog`）内的场外基金：
    场内 ETF 代码搜不到任何结果；搜名称会命中名称相关的场外基金。
    返回项含最新净值，**不含实时行情**。
    """
    logger.info(f"搜索基金: keyword={keyword}, top_n={top_n}")
    svc = FinanceApiService()
    try:
        results = svc.search_catalog(keyword=keyword, limit=top_n)
        items = [SearchItem(**item) for item in results]
        return SearchResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"搜索基金失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
