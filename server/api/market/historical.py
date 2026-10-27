"""
历史数据 API（K 线 + 分时图）

提供：
- GET /api/market/kline/{code}              K 线数据
- GET /api/market/kline/name/{name}         按名称查 K 线
- GET /api/market/intraday/{code}           当日分时图
- GET /api/market/intraday/name/{name}      按名称查分时图

2026-10-26：分时摘要（今开/最高/最低/成交量…）改为**从分时点自身汇总**，
不再依赖已下线的实时行情快照；取不到当日分钟线时返回空序列（`items=[]`），
而不是把「今天还没数据」伪装成 404 或模拟曲线。
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.services.trading_calendar import beijing_now
from server.models.schemas import (
    KlineResponse, KlineData,
    IntradayResponse, IntradayPoint,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== K 线数据 ====================


@router.get("/kline/{fund_code}", response_model=KlineResponse)
async def get_kline(
    fund_code: str,
    period: str = Query("daily"),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(None, ge=1, le=1000),
):
    """查询基金历史 K 线数据"""
    logger.info(f"查询K线数据: {fund_code}, period={period}")
    svc = FinanceApiService()
    try:
        results = svc.query_kline(
            fund_code=fund_code, period=period,
            start_date=start_date, end_date=end_date, limit=limit,
        )
        if not results:
            return KlineResponse(code=fund_code, period=period, total=0, items=[])
        items = [KlineData(**item) for item in results]
        return KlineResponse(code=fund_code, period=period, total=len(items), items=items)
    except Exception as e:
        logger.error(f"查询K线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kline/name/{fund_name}", response_model=KlineResponse)
async def get_kline_by_name(
    fund_name: str,
    period: str = Query("daily"),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(None, ge=1, le=1000),
):
    """按名称查询基金历史 K 线数据"""
    logger.info(f"按名称查询K线: {fund_name}, period={period}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        results = svc.query_kline_by_name(
            fund_name=fund_name, period=period,
            start_date=start_date, end_date=end_date, limit=limit,
        )
        items = [KlineData(**item) for item in results] if results else []
        return KlineResponse(code=fund_code, name=fund_name, period=period, total=len(items), items=items)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询K线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 分时图 ====================


def _fund_name(svc: FinanceApiService, fund_code: str) -> Optional[str]:
    """取基金名称用于响应；元数据缺失不影响分时主流程。"""
    try:
        meta = svc.fund_meta.get(fund_code)
    except Exception as e:
        logger.warning(f"读取基金元数据失败（{fund_code}）: {e}")
        return None
    return meta.fund_name if meta else None


def _intraday_response(svc: FinanceApiService, fund_code: str) -> IntradayResponse:
    """把分时点汇总成响应：摘要字段全部来自点序列本身。"""
    points: List[dict] = svc.query_intraday(fund_code)
    items = [IntradayPoint(**point) for point in points]
    if not items:
        return IntradayResponse(
            code=fund_code, name=_fund_name(svc, fund_code),
            date=beijing_now().strftime("%Y-%m-%d"),
            prev_close=0, open=0, current=0, high=0, low=0,
            change_pct=0, total_volume=0, total_amount=0,
            data_source="real", items=[],
        )

    return IntradayResponse(
        code=fund_code,
        name=_fund_name(svc, fund_code),
        date=beijing_now().strftime("%Y-%m-%d"),
        prev_close=svc._prev_close_for_intraday(fund_code),
        open=points[0].get("open") or 0,
        current=points[-1].get("price") or 0,
        high=max((p.get("high") or 0) for p in points),
        low=min((p.get("low") or 0) for p in points),
        change_pct=points[-1].get("change_pct") or 0,
        total_volume=sum((p.get("volume") or 0) for p in points),
        total_amount=sum((p.get("amount") or 0) for p in points),
        data_source="real",
        items=items,
    )


@router.get("/intraday/{fund_code}", response_model=IntradayResponse)
async def get_intraday(fund_code: str):
    """查询当日分时图数据"""
    logger.info(f"查询分时图数据: {fund_code}")
    try:
        return _intraday_response(FinanceApiService(), fund_code)
    except Exception as e:
        logger.error(f"查询分时图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intraday/name/{fund_name}", response_model=IntradayResponse)
async def get_intraday_by_name(fund_name: str):
    """按名称查询分时图"""
    logger.info(f"按名称查询分时图: {fund_name}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        return _intraday_response(svc, fund_code)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询分时图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
