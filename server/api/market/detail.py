"""
ETF 详细信息 API

提供：
- GET /api/market/detail/{code}          ETF 详细信息
- GET /api/market/detail/name/{name}     按名称查详细信息
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import (
    EtfDetailResponse, MarketData, NavHistoryItem,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 历史净值条数参数：前端按此返回的序列自切「近1月/3月/6月/1年/2年」区间
NAV_LIMIT_QUERY = Query(
    FinanceApiService.DEFAULT_NAV_LIMIT,
    ge=1,
    le=FinanceApiService.MAX_NAV_LIMIT,
    description=f"历史净值返回条数上限（默认 {FinanceApiService.DEFAULT_NAV_LIMIT}，约近2年交易日）",
)


@router.get("/detail/{fund_code}", response_model=EtfDetailResponse)
async def get_detail(fund_code: str, nav_limit: int = NAV_LIMIT_QUERY):
    """查询 ETF 详细信息（含实时行情、历史净值、费率等）"""
    logger.info(f"查询ETF详细信息: {fund_code}, nav_limit={nav_limit}")
    svc = FinanceApiService()
    try:
        result = svc.query_detail(fund_code, nav_limit=nav_limit)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金代码: {fund_code}")
        response = EtfDetailResponse(**result)
        if result.get("realtime"):
            response.realtime = MarketData(**result["realtime"])
        if result.get("nav_history"):
            response.nav_history = [NavHistoryItem(**item) for item in result["nav_history"]]
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询ETF详细信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail/name/{fund_name}", response_model=EtfDetailResponse)
async def get_detail_by_name(fund_name: str, nav_limit: int = NAV_LIMIT_QUERY):
    """按名称查询 ETF 详细信息"""
    logger.info(f"按名称查询ETF详细信息: {fund_name}, nav_limit={nav_limit}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        result = svc.query_detail(fund_code, nav_limit=nav_limit)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金: {fund_name}")
        response = EtfDetailResponse(**result)
        if result.get("realtime"):
            response.realtime = MarketData(**result["realtime"])
        if result.get("nav_history"):
            response.nav_history = [NavHistoryItem(**item) for item in result["nav_history"]]
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询ETF详细信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
