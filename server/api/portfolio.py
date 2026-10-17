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
**这组端点默认不注册**，必须显式设 ENABLE_TEST_ENDPOINTS=1 才挂载（见 _test_endpoints_enabled）。
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
    BackdateOrderRequest,
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

# 开发测试端点（/api/portfolio/test/*）在下面单独挂到这个子路由上，末尾按开关决定是否并入 router。
# 刻意不放 router 上：整组能否对外存在必须由一处代码说了算，而不是散在 8 个装饰器上。
# 刻意不带 prefix：include_router 时父 router 的前缀会再叠一次，带上会变成 /api/portfolio/portfolio/test/*
test_router = APIRouter()


#: ENABLE_TEST_ENDPOINTS 的「真」取值（大小写不敏感，前后空白忽略）
_TEST_ENDPOINT_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _test_endpoints_enabled() -> bool:
    """是否挂载 /api/portfolio/test/* 这组开发端点。**默认关**。

    为什么要有这个开关：这组端点免 JWT，只要带一个 X-User-Id 就能替任意用户下单、
    赎回、改订单确认日。原先唯一的保护是「ENV 不是 production」—— 那要求部署的人
    记得设对 ENV，而「非生产但公网可达」的机器（测试服、演示机）一旦漏设，整组就
    对全网敞开。改成默认不注册：忘了设开关的后果是「E2E 跑不了」，而不是「数据库
    被人改」，失败方向是安全的。

    跑 E2E / 本地调试时必须显式开：

        ENABLE_TEST_ENDPOINTS=1 poetry run uvicorn server.app:app --port 8000

    注意这是「注册与否」的开关，在 import 期读一次；改了必须重启进程才生效。
    _get_test_user 里的 ENV=production → 404 保留不动，作为第二道防线。
    """
    return os.getenv("ENABLE_TEST_ENDPOINTS", "").strip().lower() in _TEST_ENDPOINT_TRUTHY


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


@test_router.post("/test/apply-purchase", response_model=OrderResponse, tags=["portfolio-dev"])
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


@test_router.post("/test/apply-redeem", response_model=OrderResponse, tags=["portfolio-dev"])
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


@test_router.get("/test/positions", response_model=PositionListResponse, tags=["portfolio-dev"])
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


@test_router.get("/test/account", response_model=AccountSummaryResponse, tags=["portfolio-dev"])
async def test_account_summary(
    user_id: str = Depends(_get_test_user),
):
    """[开发] 账户概况（免 JWT）"""
    svc = PortfolioService()
    return svc.account_summary(user_id=user_id)


@test_router.get("/test/trade-flow", response_model=TradeFlowResponse, tags=["portfolio-dev"])
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


@test_router.post("/test/snapshot", response_model=SnapshotResponse, tags=["portfolio-dev"])
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


@test_router.get("/test/daily-returns", response_model=DailyReturnResponse, tags=["portfolio-dev"])
async def test_get_daily_returns(
    days: int = Query(30, ge=1, le=365),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 每日收益率（免 JWT）"""
    svc = PortfolioService()
    result = svc.get_daily_returns(user_id=user_id, days=days)
    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)


@test_router.post("/test/backdate-order", response_model=dict, tags=["portfolio-dev"])
async def test_backdate_order(
    req: BackdateOrderRequest,
    user_id: str = Depends(_get_test_user),
):
    """[开发] 把某基金最早一笔 pending 买单的确认日改到过去（免 JWT）。

    存在的理由见 PortfolioService.backdate_pending_order 的 docstring：
    E2E 一次会话内造不出「已确认持仓」（买单确认日必然 ≥ 次日），而赎回拦截
    的前提正是「已有已确认持仓 + 有 pending 买单」。改完确认日再调
    POST /api/portfolio/confirm-pending 即可得到该状态。
    """
    from server.services.portfolio_service import _beijing_date

    svc = PortfolioService()
    result = svc.backdate_pending_order(
        user_id=user_id,
        fund_code=req.fund_code,
        target_date=req.target_date or _beijing_date(),
        direction=req.direction,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ==================== 开发测试端点：按开关决定是否并入 router ====================
# 必须放在本模块末尾：上面的 8 个端点要先把路由注册到 test_router，这里才能整组并入。
# 关掉开关时它们**不进 app.routes**，也就不会出现在 /docs 与 openapi.json 里，
# 请求直接 404（不是「挂上了但拒绝」）。
if _test_endpoints_enabled():
    router.include_router(test_router)
    logger.warning(
        "ENABLE_TEST_ENDPOINTS 已开启：/api/portfolio/test/* 共 %d 个免 JWT 端点已注册，"
        "任何带 X-User-Id 的请求都能替该用户下单/赎回。只在本地与专用测试环境开。",
        len(test_router.routes),
    )
else:
    logger.info("ENABLE_TEST_ENDPOINTS 未开启，/api/portfolio/test/* 不注册（默认行为）")
