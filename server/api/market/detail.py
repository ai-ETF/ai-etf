"""
基金详细信息 API

提供：
- GET /api/market/detail/{code}          基金详细信息
- GET /api/market/detail/name/{name}     按名称查详细信息

目录外代码（场内 ETF / 非白名单基金）返回 404 + 明确原因：
`{"detail": "基金 512890 不在支持目录内"}`（2026-10-26 决策）。
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from server.services.finance_api_service import FinanceApiService
from server.services.fund_nav_service import FundNavUnavailable, FundNotSupported
from server.models.schemas import (
    EtfDetailResponse, NavHistoryItem,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _nav_unavailable(exc: FundNavUnavailable) -> HTTPException:
    """历史净值暂时不可用 → 503（不是 404：基金存在，数据还没到/取不到）。

    不能返回 200 + 空 `nav_history`：前端会把「没有历史」画成一条空曲线，
    用户看到的是「这只基金没有净值」而不是「稍后再试」。
    """
    return HTTPException(status_code=503, detail=str(exc))

# 历史净值条数参数：前端按此返回的序列自切「近1月/3月/6月/1年/2年」区间
NAV_LIMIT_QUERY = Query(
    FinanceApiService.DEFAULT_NAV_LIMIT,
    ge=1,
    le=FinanceApiService.MAX_NAV_LIMIT,
    description=f"历史净值返回条数上限（默认 {FinanceApiService.DEFAULT_NAV_LIMIT}，约近2年交易日）",
)


def _build_response(result: dict) -> EtfDetailResponse:
    """把服务层 dict 组装成响应模型（不含实时行情）。"""
    response = EtfDetailResponse(**result)
    if result.get("nav_history"):
        response.nav_history = [NavHistoryItem(**item) for item in result["nav_history"]]
    return response


@router.get("/detail/{fund_code}", response_model=EtfDetailResponse)
async def get_detail(fund_code: str, nav_limit: int = NAV_LIMIT_QUERY):
    """查询基金详细信息（含历史净值、费率等）"""
    logger.info(f"查询基金详细信息: {fund_code}, nav_limit={nav_limit}")
    svc = FinanceApiService()
    try:
        result = svc.query_detail(fund_code, nav_limit=nav_limit)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金代码: {fund_code}")
        return _build_response(result)
    except HTTPException:
        raise
    except FundNotSupported as e:
        logger.info(f"目录外基金，拒绝详情查询: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except FundNavUnavailable as e:
        logger.warning(f"历史净值暂不可用: {e}")
        raise _nav_unavailable(e)
    except Exception as e:
        logger.error(f"查询基金详细信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail/name/{fund_name}", response_model=EtfDetailResponse)
async def get_detail_by_name(fund_name: str, nav_limit: int = NAV_LIMIT_QUERY):
    """按名称查询基金详细信息"""
    logger.info(f"按名称查询基金详细信息: {fund_name}, nav_limit={nav_limit}")
    svc = FinanceApiService()
    try:
        fund_code = svc._resolve_fund_code(fund_name)
        if not fund_code:
            raise HTTPException(status_code=404, detail=f"无法识别基金名称: {fund_name}")
        result = svc.query_detail(fund_code, nav_limit=nav_limit)
        if not result:
            raise HTTPException(status_code=404, detail=f"未找到基金: {fund_name}")
        return _build_response(result)
    except HTTPException:
        raise
    except FundNotSupported as e:
        logger.info(f"目录外基金，拒绝详情查询: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except FundNavUnavailable as e:
        logger.warning(f"历史净值暂不可用: {e}")
        raise _nav_unavailable(e)
    except Exception as e:
        logger.error(f"查询基金详细信息失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
