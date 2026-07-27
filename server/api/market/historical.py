"""
历史数据 API（K 线 + 分时图）

提供：
- GET /api/market/kline/{code}              K 线数据
- GET /api/market/kline/name/{name}         按名称查 K 线
- GET /api/market/intraday/{code}           当日分时图
- GET /api/market/intraday/name/{name}      按名称查分时图
"""

import logging

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
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
    """查询 ETF 历史 K 线数据"""
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
    """按名称查询 ETF 历史 K 线数据"""
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


@router.get("/intraday/{fund_code}", response_model=IntradayResponse)
async def get_intraday(fund_code: str):
    """查询当日分时图数据"""
    logger.info(f"查询分时图数据: {fund_code}")
    svc = FinanceApiService()
    try:
        spot = svc.query_spot(fund_code)
        if not spot:
            raise HTTPException(status_code=404, detail=f"未找到基金代码: {fund_code}")
        items = svc.query_intraday(fund_code)
        ds = "real" if (items and "amount" in items[0]) else "simulated"
        return IntradayResponse(
            code=fund_code, name=spot.get("name", ""),
            date=spot.get("data_date", ""), prev_close=spot.get("prev_close", 0),
            open=spot.get("open", 0), current=spot.get("price", 0),
            high=spot.get("high", 0), low=spot.get("low", 0),
            change_pct=spot.get("change_pct", 0),
            total_volume=spot.get("volume", 0), total_amount=spot.get("amount", 0),
            data_source=ds, items=[IntradayPoint(**item) for item in items],
        )
    except HTTPException:
        raise
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
        spot = svc.query_spot(fund_code)
        if not spot:
            raise HTTPException(status_code=404, detail=f"未找到基金: {fund_name}")
        items = svc.query_intraday(fund_code)
        ds = "simulated" if (items and items[0].get("time", "").startswith("09")) else "real"
        return IntradayResponse(
            code=fund_code, name=spot.get("name", ""),
            date=spot.get("data_date", ""), prev_close=spot.get("prev_close", 0),
            open=spot.get("open", 0), current=spot.get("price", 0),
            high=spot.get("high", 0), low=spot.get("low", 0),
            change_pct=spot.get("change_pct", 0),
            total_volume=spot.get("volume", 0), total_amount=spot.get("amount", 0),
            data_source=ds, items=[IntradayPoint(**item) for item in items],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询分时图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
