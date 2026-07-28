"""
实时行情 + 榜单 API（高频查询）

提供：
- GET /api/market/spot/{code}        单只 ETF 实时行情
- GET /api/market/spot/name/{name}   按名称查实时行情
- GET /api/market/ranking            涨幅榜/跌幅榜
"""

import logging

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import MarketResponse, RankingResponse, RankingItem

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/spot/{fund_code}", response_model=MarketResponse)
async def get_spot(fund_code: str):
    """查询单只 ETF 实时行情"""
    logger.info(f"查询ETF实时行情: {fund_code}")
    svc = FinanceApiService()
    try:
        data = svc.query_spot(fund_code)
        if not data:
            return MarketResponse(error=f"未找到基金代码: {fund_code}")
        return MarketResponse(data=data)
    except Exception as e:
        logger.error(f"查询行情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spot/name/{fund_name}", response_model=MarketResponse)
async def get_spot_by_name(fund_name: str):
    """按名称查询 ETF 实时行情"""
    logger.info(f"按名称查询ETF实时行情: {fund_name}")
    svc = FinanceApiService()
    try:
        data = svc.query_spot_by_name(fund_name)
        if not data:
            return MarketResponse(error=f"无法识别基金名称: {fund_name}")
        return MarketResponse(data=data)
    except Exception as e:
        logger.error(f"查询行情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ranking", response_model=RankingResponse)
async def get_ranking(
    sort_by: str = Query("涨跌幅", description="排序字段"),
    top_n: int = Query(10, ge=1, le=50),
    order: str = Query("desc", description="desc=涨幅榜, asc=跌幅榜"),
):
    """查询 ETF 涨幅榜 / 跌幅榜"""
    logger.info(f"查询ETF榜单: sort_by={sort_by}, top_n={top_n}, order={order}")
    svc = FinanceApiService()
    try:
        ascending = order == "asc"
        results = svc.query_ranking(sort_by=sort_by, top_n=top_n, ascending=ascending)
        items = [RankingItem(**item) for item in results]
        return RankingResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"查询榜单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
