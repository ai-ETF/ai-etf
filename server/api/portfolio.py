"""
场外基金持仓交易 API 端点

提供：
- POST /portfolio/apply-purchase — 按金额申购
- POST /portfolio/apply-redeem  — 按份额赎回
- GET  /portfolio/positions      — 持仓列表
- GET  /portfolio/account        — 账户概况
- GET  /portfolio/trade-flow     — 交易流水
- POST /portfolio/snapshot       — 手动创建快照
- GET  /portfolio/daily-returns  — 每日收益率
- GET  /portfolio/health         — 健康检查（公开）

开发环境：/api/portfolio/test/* 端点免 JWT 认证，用 X-User-Id header 指定用户。
"""
import logging
import os
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header

from server.auth import get_current_user
from server.models.schemas import (
    PurchaseRequest,
    RedeemRequest,
    OrderResponse,
    OrderResult,
    RiskWarning,
    PositionListResponse,
    PositionItem,
    AccountSummaryResponse,
    TradeFlowResponse,
    TradeFlowItem,
    SnapshotResponse,
    SnapshotData,
    DailyReturnResponse,
    DailyReturnItem,
    AutoInvestConfigRequest,
    AutoInvestConfigResponse,
)
from server.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _get_test_user(x_user_id: Optional[str] = Header(None)) -> str:
    """开发测试：从 X-User-Id header 获取用户 ID，不校验 JWT。仅非生产环境可用。"""
    if os.getenv("ENV", "").lower() == "production":
        raise HTTPException(status_code=404, detail="Not Found")
    if not x_user_id:
        raise HTTPException(status_code=400, detail="请传入 X-User-Id header")
    return x_user_id


# ==================== 正式端点（需 JWT） ====================


@router.post("/apply-purchase", response_model=OrderResponse)
async def apply_purchase(
    req: PurchaseRequest,
    current_user: str = Depends(get_current_user),
):
    """
    场外基金按金额申购（需 JWT 认证）

    - 15:00 前提交：立即成交，按当日净值确认
    - 15:00 后提交：pending，资金冻结，下一交易日确认
    - 申购费按外扣法计算
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_purchase(
        user_id=current_user,
        fund_code=req.fund_code,
        amount=Decimal(str(req.amount)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return OrderResponse(
        success=True,
        message=result["message"],
        data=OrderResult(**result["data"]) if result["data"] else None,
        risk_warning=RiskWarning(**result["risk_warning"]) if result.get("risk_warning") else None,
    )


@router.post("/apply-redeem", response_model=OrderResponse)
async def apply_redeem(
    req: RedeemRequest,
    current_user: str = Depends(get_current_user),
):
    """
    场外基金按份额赎回（需 JWT 认证）

    - 赎回费按持有天数档位计算
    - 赎回后持仓清零则删除记录
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_redeem(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return OrderResponse(
        success=True,
        message=result["message"],
        data=OrderResult(**result["data"]) if result["data"] else None,
    )


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(
    include_quote: bool = Query(True, description="是否按实时行情计算市值和盈亏"),
    current_user: str = Depends(get_current_user),
):
    """查询持仓列表（需 JWT 认证）"""
    svc = PortfolioService()
    result = svc.list_positions(user_id=current_user, include_quote=include_quote)
    items = [PositionItem(**item) for item in result["items"]]
    return PositionListResponse(
        total=result["total"],
        items=items,
        total_pnl=result["total_pnl"],
        total_position_value=result["total_position_value"],
    )


@router.get("/account", response_model=AccountSummaryResponse)
async def account_summary(
    current_user: str = Depends(get_current_user),
):
    """查询账户概况（需 JWT 认证）"""
    svc = PortfolioService()
    return svc.account_summary(user_id=current_user)


@router.get("/trade-flow", response_model=TradeFlowResponse)
async def query_trade_flow(
    fund_code: Optional[str] = Query(None, description="基金代码（可选过滤）"),
    direction: Optional[str] = Query(None, description="方向 buy/sell（可选过滤）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    current_user: str = Depends(get_current_user),
):
    """分页查询交易流水（需 JWT 认证）"""
    svc = PortfolioService()
    result = svc.query_trade_flow(
        user_id=current_user,
        fund_code=fund_code,
        direction=direction,
        page=page,
        page_size=page_size,
    )
    items = [TradeFlowItem(**item) for item in result["items"]]
    return TradeFlowResponse(
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
        items=items,
    )


@router.post("/snapshot", response_model=SnapshotResponse)
async def take_snapshot(
    current_user: str = Depends(get_current_user),
):
    """手动创建当日资产快照（需 JWT 认证）"""
    svc = PortfolioService()
    result = svc.take_snapshot(user_id=current_user)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])

    return SnapshotResponse(
        success=True,
        message=result["message"],
        data=SnapshotData(**result["data"]) if result["data"] else None,
    )


@router.post("/confirm-pending", response_model=dict)
async def confirm_pending(current_user: str = Depends(get_current_user)):
    """手动触发 pending 订单确认（需 JWT 认证）。"""
    svc = PortfolioService()
    result = svc.confirm_pending_orders(skip_trading_day_check=True)
    return result


@router.get("/daily-returns", response_model=DailyReturnResponse)
async def get_daily_returns(
    days: int = Query(30, ge=1, le=365, description="查询最近多少天"),
    current_user: str = Depends(get_current_user),
):
    """查询每日收益率（需 JWT 认证）"""
    svc = PortfolioService()
    result = svc.get_daily_returns(user_id=current_user, days=days)
    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)


@router.get("/health")
async def health_check():
    """健康检查（公开）"""
    return {"status": "ok", "service": "portfolio"}


# ==================== 余额理财开关 ====================


@router.get("/auto-invest/config", response_model=AutoInvestConfigResponse)
async def get_auto_invest_config(current_user: str = Depends(get_current_user)):
    """查询余额理财开关状态"""
    from server.services.portfolio_service import PortfolioService, MONEY_FUND_CODE
    svc = PortfolioService()
    config = svc.get_auto_invest_config(current_user)
    return AutoInvestConfigResponse(**config)


@router.post("/auto-invest/config", response_model=AutoInvestConfigResponse)
async def set_auto_invest_config(
    req: AutoInvestConfigRequest,
    current_user: str = Depends(get_current_user),
):
    """设置余额理财开关和预留金额"""
    from server.services.portfolio_service import PortfolioService, MONEY_FUND_CODE
    svc = PortfolioService()
    config = svc.set_auto_invest_config(current_user, req.enabled, req.reserve or 0.0)
    return AutoInvestConfigResponse(**config)


# ==================== 开发测试端点（免 JWT，用 X-User-Id header） ====================


@router.post("/test/apply-purchase", response_model=OrderResponse, tags=["portfolio-dev"])
async def test_apply_purchase(
    req: PurchaseRequest,
    user_id: str = Depends(_get_test_user),
):
    """[开发] 按金额申购（免 JWT）"""
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_purchase(
        user_id=user_id,
        fund_code=req.fund_code,
        amount=Decimal(str(req.amount)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return OrderResponse(
        success=True,
        message=result["message"],
        data=OrderResult(**result["data"]) if result["data"] else None,
        risk_warning=RiskWarning(**result["risk_warning"]) if result.get("risk_warning") else None,
    )


@router.post("/test/apply-redeem", response_model=OrderResponse, tags=["portfolio-dev"])
async def test_apply_redeem(
    req: RedeemRequest,
    user_id: str = Depends(_get_test_user),
):
    """[开发] 按份额赎回（免 JWT）"""
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_redeem(
        user_id=user_id,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return OrderResponse(
        success=True,
        message=result["message"],
        data=OrderResult(**result["data"]) if result["data"] else None,
    )


@router.get("/test/positions", response_model=PositionListResponse, tags=["portfolio-dev"])
async def test_list_positions(
    include_quote: bool = Query(True),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 持仓列表（免 JWT）"""
    svc = PortfolioService()
    result = svc.list_positions(user_id=user_id, include_quote=include_quote)
    items = [PositionItem(**item) for item in result["items"]]
    return PositionListResponse(
        total=result["total"],
        items=items,
        total_pnl=result["total_pnl"],
        total_position_value=result["total_position_value"],
    )


@router.get("/test/account", response_model=AccountSummaryResponse, tags=["portfolio-dev"])
async def test_account_summary(
    user_id: str = Depends(_get_test_user),
):
    """[开发] 账户概况（免 JWT）"""
    svc = PortfolioService()
    return svc.account_summary(user_id=user_id)


@router.get("/test/trade-flow", response_model=TradeFlowResponse, tags=["portfolio-dev"])
async def test_query_trade_flow(
    fund_code: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 交易流水（免 JWT）"""
    svc = PortfolioService()
    result = svc.query_trade_flow(
        user_id=user_id,
        fund_code=fund_code,
        direction=direction,
        page=page,
        page_size=page_size,
    )
    items = [TradeFlowItem(**item) for item in result["items"]]
    return TradeFlowResponse(
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"],
        items=items,
    )


@router.post("/test/snapshot", response_model=SnapshotResponse, tags=["portfolio-dev"])
async def test_take_snapshot(
    user_id: str = Depends(_get_test_user),
):
    """[开发] 创建快照（免 JWT）"""
    svc = PortfolioService()
    result = svc.take_snapshot(user_id=user_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    return SnapshotResponse(
        success=True,
        message=result["message"],
        data=SnapshotData(**result["data"]) if result["data"] else None,
    )


@router.get("/test/daily-returns", response_model=DailyReturnResponse, tags=["portfolio-dev"])
async def test_get_daily_returns(
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 每日收益率（免 JWT）"""
    svc = PortfolioService()
    result = svc.get_daily_returns(user_id=user_id, days=days)
    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)