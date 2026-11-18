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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Header

from server.api.admin import require_admin_token
from server.auth import get_current_user
from server.models.schemas import (
    PurchaseRequest,
    RedeemRequest,
    OrderResponse,
    OrderResult,
    CancelOrderResponse,
    CancelOrderResult,
    RiskWarning,
    PositionListResponse,
    PositionItem,
    AccountSummaryResponse,
    PortfolioOverviewResponse,
    TradeFlowResponse,
    TradeFlowItem,
    SnapshotResponse,
    SnapshotData,
    ConfirmRunResponse,
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
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key",
        description="下单幂等键；重复提交返回既有订单，不重复冻结资金",
    ),
):
    """
    场外基金按金额申购（需 JWT 认证）

    - 15:00 前提交：当日为受理日（T），按 T 日净值确认，份额 T+N 到账
    - 15:00 后提交：pending，资金立即冻结，下一交易日为受理日
    - 申购费按外扣法计算；`Idempotency-Key` 传入时同一键只建一单
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_purchase(
        user_id=current_user,
        fund_code=req.fund_code,
        amount=Decimal(str(req.amount)),
        price=price,
        client_order_id=idempotency_key,
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
    idempotency_key: Optional[str] = Header(
        default=None, alias="Idempotency-Key",
        description="赎回幂等键；重复提交返回既有订单，不重复占份额",
    ),
):
    """
    场外基金按份额赎回（需 JWT 认证）

    - 按 FIFO 从可赎回批次卖出，赎回费逐段按持有天数计算
    - 有在途申购时不可赎回（pending_purchase）
    - 到账日 = 受理日 T + 基金到账延迟交易日
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.apply_redeem(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
        client_order_id=idempotency_key,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return OrderResponse(
        success=True,
        message=result["message"],
        data=OrderResult(**result["data"]) if result["data"] else None,
    )


@router.post("/orders/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(
    order_id: UUID,
    current_user: str = Depends(get_current_user),
):
    """
    撤销待确认订单（需 JWT 认证）

    - 仅 `pending` 订单可撤，且必须在**受理日 15:00 前**提交
    - 买入撤单：冻结资金原路退回可用现金
    - 卖出撤单：释放被占用的可赎份额
    - 退款/释放份额/状态变更在同一数据库事务内完成；重复撤单幂等返回
    """
    svc = PortfolioService()
    result = svc.cancel_order(user_id=current_user, order_id=str(order_id))
    if not result["success"]:
        raise HTTPException(
            status_code=result.get("status_code", 400),
            detail=result["message"],
        )

    return CancelOrderResponse(
        success=True,
        message=result["message"],
        data=CancelOrderResult(**result["data"]) if result["data"] else None,
    )


def _to_position_list_response(result: dict) -> PositionListResponse:
    """把服务层返回的持仓字典转成响应模型（/positions 与 /overview 共用）。"""
    return PositionListResponse(
        total=result["total"],
        items=[PositionItem(**item) for item in result["items"]],
        total_pnl=result["total_pnl"],
        total_position_value=result["total_position_value"],
    )


# 同步函数（def）：服务层是同步的 Supabase 调用，交给 FastAPI 线程池执行，
# 避免阻塞事件循环导致并发请求排队。
@router.get("/positions", response_model=PositionListResponse)
def list_positions(
    include_quote: bool = Query(True, description="是否按实时行情计算市值和盈亏"),
    current_user: str = Depends(get_current_user),
):
    """查询持仓列表（需 JWT 认证）"""
    svc = PortfolioService()
    result = svc.list_positions(user_id=current_user, include_quote=include_quote)
    return _to_position_list_response(result)


@router.get("/account", response_model=AccountSummaryResponse)
def account_summary(
    current_user: str = Depends(get_current_user),
):
    """查询账户概况（需 JWT 认证）"""
    svc = PortfolioService()
    return svc.account_summary(user_id=current_user)


@router.get("/overview", response_model=PortfolioOverviewResponse)
def portfolio_overview(
    current_user: str = Depends(get_current_user),
):
    """持仓页一次读取账户概况与持仓列表（需 JWT 认证）。

    替代页面并行请求 `/account` + `/positions`：后端只算一次持仓，
    页面只发一个请求。旧的两个端点保留，供其他页面继续使用。
    """
    svc = PortfolioService()
    result = svc.portfolio_overview(user_id=current_user)
    return PortfolioOverviewResponse(
        account=AccountSummaryResponse(**result["account"]),
        positions=_to_position_list_response(result["positions"]),
    )


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
    """确保最近一个交易日的账户快照存在且有效（需 JWT 认证）。

    幂等：已有有效快照直接返回，不重复写入。非交易日或 T 日净值未齐返回 409；
    交易日历不可用返回 503。
    """
    from server.services.account_snapshot_service import NotTradingDay, ValuationNotReady
    from server.services.trading_calendar import CalendarOutOfCoverage, CalendarUnavailable

    svc = PortfolioService()
    try:
        result = svc.take_snapshot(user_id=current_user)
    except (NotTradingDay, ValuationNotReady) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
        raise HTTPException(status_code=503, detail=f"交易日历不可用: {exc}")

    return SnapshotResponse(
        success=True,
        message=result["message"],
        data=SnapshotData(**result["data"]) if result["data"] else None,
    )


@router.post("/confirm-pending", response_model=ConfirmRunResponse)
async def confirm_pending(_: None = Depends(require_admin_token)):
    """手动触发一轮 pending 订单确认（需 `X-Admin-Token`，未配置时 503）。

    扫描条件：`status='pending' AND confirm_date <= today`。确认日等于今天且当前
    早于 10:00 的订单保持 pending（计入 `skipped_time`）；取不到 T 日净值的订单
    保持 pending（计入 `skipped_nav`）；已有批次在跑时返回 `status='busy'`
    （HTTP 200，不是失败）。响应字段见 `ConfirmRunResponse`。
    """
    svc = PortfolioService()
    return svc.confirm_pending_orders()


@router.get("/daily-returns", response_model=DailyReturnResponse)
async def get_daily_returns(
    days: int = Query(30, ge=1, le=365, description="查询最近多少天"),
    current_user: str = Depends(get_current_user),
):
    """查询每日/区间收益率（需 JWT 认证）。

    只基于 `status='valid'` 的快照；缺口日 `daily_return=null`，同时给出
    `period_days` 与 `period_return`。数据库或交易日历异常返回 503。
    """
    from server.services.trading_calendar import CalendarOutOfCoverage, CalendarUnavailable

    svc = PortfolioService()
    try:
        result = svc.get_daily_returns(user_id=current_user, days=days)
    except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
        raise HTTPException(status_code=503, detail=f"交易日历不可用: {exc}")
    except Exception as exc:
        logger.exception("查询每日收益失败: user=%s days=%s", current_user, days)
        raise HTTPException(status_code=503, detail=f"查询每日收益失败: {exc}")

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
def test_list_positions(
    include_quote: bool = Query(True),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 持仓列表（免 JWT）"""
    svc = PortfolioService()
    result = svc.list_positions(user_id=user_id, include_quote=include_quote)
    return _to_position_list_response(result)


@router.get("/test/account", response_model=AccountSummaryResponse, tags=["portfolio-dev"])
def test_account_summary(
    user_id: str = Depends(_get_test_user),
):
    """[开发] 账户概况（免 JWT）"""
    svc = PortfolioService()
    return svc.account_summary(user_id=user_id)


@router.get("/test/overview", response_model=PortfolioOverviewResponse, tags=["portfolio-dev"])
def test_portfolio_overview(
    user_id: str = Depends(_get_test_user),
):
    """[开发] 持仓页概况（免 JWT）"""
    svc = PortfolioService()
    result = svc.portfolio_overview(user_id=user_id)
    return PortfolioOverviewResponse(
        account=AccountSummaryResponse(**result["account"]),
        positions=_to_position_list_response(result["positions"]),
    )


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
    """[开发] 确保最近一个交易日的账户快照（免 JWT）"""
    from server.services.account_snapshot_service import NotTradingDay, ValuationNotReady
    from server.services.trading_calendar import CalendarOutOfCoverage, CalendarUnavailable

    svc = PortfolioService()
    try:
        result = svc.take_snapshot(user_id=user_id)
    except (NotTradingDay, ValuationNotReady) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
        raise HTTPException(status_code=503, detail=f"交易日历不可用: {exc}")
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
    from server.services.trading_calendar import CalendarOutOfCoverage, CalendarUnavailable

    svc = PortfolioService()
    try:
        result = svc.get_daily_returns(user_id=user_id, days=days)
    except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
        raise HTTPException(status_code=503, detail=f"交易日历不可用: {exc}")
    except Exception as exc:
        logger.exception("查询每日收益失败: user=%s days=%s", user_id, days)
        raise HTTPException(status_code=503, detail=f"查询每日收益失败: {exc}")

    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)