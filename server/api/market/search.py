"""
ETF 搜索 / 筛选 / 分类 API

提供：
- GET  /api/market/search?keyword=      搜索 ETF
- POST /api/market/filter               高级筛选 ETF
- GET  /api/market/categories           分类列表
- GET  /api/market/category/{cat}       分类下基金列表
"""

import logging

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import (
    SearchResponse, SearchItem, FilterRequest,
    CategoryListResponse, FundCategory,
    FundListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search_etf(
    keyword: str = Query(..., description="搜索关键词"),
    top_n: int = Query(10, ge=1, le=50),
    include_quote: bool = Query(True),
):
    """搜索 ETF（按名称或代码模糊匹配）"""
    logger.info(f"搜索ETF: keyword={keyword}, top_n={top_n}")
    svc = FinanceApiService()
    try:
        results = svc.search_etf(keyword=keyword, top_n=top_n, include_quote=include_quote)
        items = [SearchItem(**item) for item in results]
        return SearchResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"搜索ETF失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/filter", response_model=SearchResponse)
async def filter_etf(req: FilterRequest):
    """高级筛选 ETF（费率、规模、涨跌幅等条件）"""
    logger.info(f"筛选ETF: sort_by={req.sort_by}")
    svc = FinanceApiService()
    try:
        filters = req.dict(exclude_none=True)
        results = svc.filter_etf(filters)
        items = [SearchItem(**item) for item in results]
        return SearchResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"筛选ETF失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories", response_model=CategoryListResponse)
async def get_categories():
    """获取 ETF 分类列表"""
    logger.info("获取ETF分类列表")
    svc = FinanceApiService()
    try:
        results = svc.get_categories()
        total_funds = sum(c["count"] for c in results)
        items = [FundCategory(**item) for item in results]
        return CategoryListResponse(total_categories=len(items), total_funds=total_funds, items=items)
    except Exception as e:
        logger.error(f"获取分类列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/category/{category}", response_model=FundListResponse)
async def get_category_funds(
    category: str,
    top_n: int = Query(50, ge=1, le=100),
):
    """获取指定分类下的 ETF 列表"""
    logger.info(f"获取分类ETF: category={category}, top_n={top_n}")
    svc = FinanceApiService()
    try:
        results = svc.get_category_funds(category=category, top_n=top_n)
        items = [SearchItem(**item) for item in results]
        return FundListResponse(category=category, total=len(items), items=items)
    except Exception as e:
        logger.error(f"获取分类ETF失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
