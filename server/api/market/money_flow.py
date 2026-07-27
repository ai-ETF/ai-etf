"""
资金流向 API

提供：
- GET /api/market/money-flow/{code}           单只 ETF 资金流向
- GET /api/market/money-flow/name/{name}      按名称查资金流向
- GET /api/market/money-flow/ranking          资金流向排行榜
"""

import logging

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import (
    MoneyFlowData, MoneyFlowRankingItem, MoneyFlowRankingResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/money-flow/{fund_code}", response_model=MoneyFlowData)
async def get_money_flow(fund_code: str):
    """查询单只 ETF 资金流向"""
    logger.info(f"查询资金流向: {fund_code}")
    svc = FinanceApiService()
    try:
        result = svc.query_money_flow(fund_code)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金代码: {fund_code}")
        return MoneyFlowData(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询资金流向失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/money-flow/name/{fund_name}", response_model=MoneyFlowData)
async def get_money_flow_by_name(fund_name: str):
    """按名称查询资金流向"""
    logger.info(f"按名称查询资金流向: {fund_name}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        result = svc.query_money_flow(fund_code)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金: {fund_name}")
        return MoneyFlowData(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询资金流向失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/money-flow/ranking", response_model=MoneyFlowRankingResponse)
async def get_money_flow_ranking(
    top_n: int = Query(20, ge=1, le=50),
    order: str = Query("desc", description="desc=净流入榜, asc=净流出榜"),
):
    """查询资金流向排行榜"""
    logger.info(f"查询资金流向榜: top_n={top_n}, order={order}")
    svc = FinanceApiService()
    try:
        ascending = order == "asc"
        results = svc.query_money_flow_ranking(top_n=top_n, ascending=ascending)
        items = [MoneyFlowRankingItem(**item) for item in results]
        return MoneyFlowRankingResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"查询资金流向榜失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
