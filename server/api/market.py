"""
ETF 实时行情 API 端点

提供独立的行情查询接口，支持：
1. 单只ETF实时行情查询
2. ETF涨幅榜/跌幅榜查询
3. ETF历史K线数据查询
"""

from fastapi import APIRouter, Query, HTTPException
from server.services.finance_api_service import FinanceApiService
from server.models.schemas import (
    MarketResponse, RankingResponse, RankingItem,
    KlineResponse, KlineData,
    EtfDetailResponse, NavHistoryItem, MarketData,
    SearchResponse, SearchItem, FilterRequest,
    CategoryListResponse, FundCategory,
    FundListResponse,
    IntradayResponse, IntradayPoint,
    MoneyFlowData, MoneyFlowRankingItem, MoneyFlowRankingResponse,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/spot/{fund_code}", response_model=MarketResponse)
async def get_spot(fund_code: str):
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
    order: str = Query("desc", description="desc=涨幅榜, asc=跌幅榜")
):
    logger.info(f"查询ETF榜单: sort_by={sort_by}, top_n={top_n}, order={order}")
    svc = FinanceApiService()
    try:
        ascending = (order == "asc")
        results = svc.query_ranking(sort_by=sort_by, top_n=top_n, ascending=ascending)
        items = [RankingItem(**item) for item in results]
        return RankingResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"查询榜单失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "market"}


# ==================== K线数据查询API ====================

@router.get("/kline/{fund_code}", response_model=KlineResponse)
async def get_kline(
    fund_code: str,
    period: str = Query("daily"),
    start_date: str = Query(None),
    end_date: str = Query(None),
    limit: int = Query(None, ge=1, le=1000)
):
    logger.info(f"查询K线数据: {fund_code}, period={period}")
    svc = FinanceApiService()
    try:
        results = svc.query_kline(fund_code=fund_code, period=period, start_date=start_date, end_date=end_date, limit=limit)
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
    limit: int = Query(None, ge=1, le=1000)
):
    logger.info(f"按名称查询K线: {fund_name}, period={period}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        results = svc.query_kline_by_name(fund_name=fund_name, period=period, start_date=start_date, end_date=end_date, limit=limit)
        items = [KlineData(**item) for item in results] if results else []
        return KlineResponse(code=fund_code, name=fund_name, period=period, total=len(items), items=items)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询K线失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== ETF详细信息查询API ====================

@router.get("/detail/{fund_code}", response_model=EtfDetailResponse)
async def get_detail(fund_code: str):
    logger.info(f"查询ETF详细信息: {fund_code}")
    svc = FinanceApiService()
    try:
        result = svc.query_detail(fund_code)
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
async def get_detail_by_name(fund_name: str):
    logger.info(f"按名称查询ETF详细信息: {fund_name}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        result = svc.query_detail(fund_code)
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


# ==================== ETF搜索/筛选API ====================

@router.get("/search", response_model=SearchResponse)
async def search_etf(
    keyword: str = Query(..., description="搜索关键词"),
    top_n: int = Query(10, ge=1, le=50),
    include_quote: bool = Query(True)
):
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
async def get_category_funds(category: str, top_n: int = Query(50, ge=1, le=100)):
    logger.info(f"获取分类ETF: category={category}, top_n={top_n}")
    svc = FinanceApiService()
    try:
        results = svc.get_category_funds(category=category, top_n=top_n)
        items = [SearchItem(**item) for item in results]
        return FundListResponse(category=category, total=len(items), items=items)
    except Exception as e:
        logger.error(f"获取分类ETF失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 分时图API（新增） ====================

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
            code=fund_code, name=spot.get("name",""),
            date=spot.get("data_date",""), prev_close=spot.get("prev_close",0),
            open=spot.get("open",0), current=spot.get("price",0),
            high=spot.get("high",0), low=spot.get("low",0),
            change_pct=spot.get("change_pct",0),
            total_volume=spot.get("volume",0), total_amount=spot.get("amount",0),
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
        ds = "simulated" if (items and items[0].get("time","").startswith("09")) else "real"
        return IntradayResponse(
            code=fund_code, name=spot.get("name",""),
            date=spot.get("data_date",""), prev_close=spot.get("prev_close",0),
            open=spot.get("open",0), current=spot.get("price",0),
            high=spot.get("high",0), low=spot.get("low",0),
            change_pct=spot.get("change_pct",0),
            total_volume=spot.get("volume",0), total_amount=spot.get("amount",0),
            data_source=ds, items=[IntradayPoint(**item) for item in items],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询分时图失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 资金流向API（新增） ====================

@router.get("/money-flow/{fund_code}", response_model=MoneyFlowData)
async def get_money_flow(fund_code: str):
    """查询单只ETF资金流向"""
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
    order: str = Query("desc", description="desc=净流入榜, asc=净流出榜")
):
    """查询资金流向排行榜"""
    logger.info(f"查询资金流向榜: top_n={top_n}, order={order}")
    svc = FinanceApiService()
    try:
        ascending = (order == "asc")
        results = svc.query_money_flow_ranking(top_n=top_n, ascending=ascending)
        items = [MoneyFlowRankingItem(**item) for item in results]
        return MoneyFlowRankingResponse(total=len(items), items=items)
    except Exception as e:
        logger.error(f"查询资金流向榜失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
