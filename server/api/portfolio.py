"""
模拟持仓交易 API 端点

提供：
- POST /portfolio/buy — 买入
- POST /portfolio/sell — 卖出
- GET  /portfolio/positions — 持仓列表
- GET  /portfolio/account — 账户概况
- GET  /portfolio/trade-flow — 交易流水
- POST /portfolio/snapshot — 手动创建快照
- GET  /portfolio/daily-returns — 每日收益率
- GET  /portfolio/health — 健康检查（公开）

❗ 开发环境：/api/portfolio/test/* 端点免 JWT 认证，用 X-User-Id header 指定用户。
"""
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header

from server.auth import get_current_user
from server.models.schemas import (
    TradeRequest,
    TradeResponse,
    TradeData,
    PositionListResponse,
    PositionItem,
    AccountSummaryResponse,
    TradeFlowResponse,
    TradeFlowItem,
    SnapshotResponse,
    SnapshotData,
    DailyReturnResponse,
    DailyReturnItem,
    ReserveRequest,
    ReservationResponse,
    ReservationItem,
    ReservationListResponse,
)
from server.services.portfolio_service import PortfolioService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _get_test_user(x_user_id: Optional[str] = Header(None)) -> str:
    """开发测试：从 X-User-Id header 获取用户 ID，不校验 JWT"""
    if not x_user_id:
        raise HTTPException(status_code=400, detail="请传入 X-User-Id header")
    return x_user_id


# ==================== 正式端点（需 JWT） ====================


@router.post("/buy", response_model=TradeResponse)
async def buy(
    req: TradeRequest,
    current_user: str = Depends(get_current_user),
):
    """
    买入基金（需 JWT 认证）

    - 校验可用现金是否充足
    - 校验最低申购金额
    - 按加权平均法计算新成本价
    - 自动扣除手续费
    - 写入交易流水
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.buy(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return TradeResponse(
        success=True,
        message=result["message"],
        data=TradeData(**result["data"]) if result["data"] else None,
    )


@router.post("/sell", response_model=TradeResponse)
async def sell(
    req: TradeRequest,
    current_user: str = Depends(get_current_user),
):
    """
    卖出基金（需 JWT 认证）

    - 校验持仓数量是否充足
    - 按持有天数计算赎回费
    - 卖完后持仓清空则删除持仓记录
    - 写入交易流水
    """
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.sell(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return TradeResponse(
        success=True,
        message=result["message"],
        data=TradeData(**result["data"]) if result["data"] else None,
    )


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(
    include_quote: bool = Query(True, description="是否按实时行情计算市值和盈亏"),
    current_user: str = Depends(get_current_user),
):
    """
    查询持仓列表（需 JWT 认证）

    include_quote=true 时，自动按当前价格计算每只持仓的市值和盈亏。
    """
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
    """
    查询账户概况（需 JWT 认证）

    返回：
    - cash: 可用现金
    - position_value: 持仓市值
    - total_assets: 总资产 = 现金 + 持仓市值
    - total_pnl: 总盈亏
    - total_return_rate: 总收益率
    - position_count: 持仓基金数
    """
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
    """
    分页查询交易流水（需 JWT 认证）

    支持按基金代码和交易方向过滤，按时间倒序排列。
    """
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
    """
    手动创建当日资产快照（需 JWT 认证）

    同一天已存在快照会覆盖更新。
    通常在日终定时任务调用，也支持手动触发。
    """
    svc = PortfolioService()
    result = svc.take_snapshot(user_id=current_user)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])

    return SnapshotResponse(
        success=True,
        message=result["message"],
        data=SnapshotData(**result["data"]) if result["data"] else None,
    )


@router.get("/daily-returns", response_model=DailyReturnResponse)
async def get_daily_returns(
    days: int = Query(30, ge=1, le=365, description="查询最近多少天"),
    current_user: str = Depends(get_current_user),
):
    """
    查询每日收益率（需 JWT 认证）

    返回指定天数内的每日资产快照及日收益率。
    日收益率 = (今日总资产 - 昨日总资产) / 昨日总资产
    """
    svc = PortfolioService()
    result = svc.get_daily_returns(user_id=current_user, days=days)

    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)


@router.get("/health")
async def health_check():
    """健康检查（公开）"""
    return {"status": "ok", "service": "portfolio"}


# ==================== ETF 预约端点（需 JWT） ====================


@router.post("/reserve-buy", response_model=ReservationResponse)
async def reserve_buy(
    req: ReserveRequest,
    current_user: str = Depends(get_current_user),
):
    """
    预约买入 ETF（非交易时段提交，到下一交易时段自动成交）

    仅支持场内 ETF，非交易时段可用。交易时段请直接使用 /buy。
    - 预约时不扣款，成交时按实时价执行
    - 100 份整数倍
    - 可通过 /reservations 查看预约状态
    - 可通过 /cancel-reservation/{order_id} 取消
    """
    svc = PortfolioService()
    result = svc.create_reservation(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        direction="buy",
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ReservationResponse(
        success=True,
        message=result["message"],
        data=ReservationItem(**result["data"]) if result["data"] else None,
    )


@router.post("/reserve-sell", response_model=ReservationResponse)
async def reserve_sell(
    req: ReserveRequest,
    current_user: str = Depends(get_current_user),
):
    """
    预约卖出 ETF（非交易时段提交，到下一交易时段自动成交）

    仅支持场内 ETF，非交易时段可用。交易时段请直接使用 /sell。
    - 预约时不入账，成交时按实时价执行
    - 100 份整数倍
    - 可通过 /reservations 查看预约状态
    - 可通过 /cancel-reservation/{order_id} 取消
    """
    svc = PortfolioService()
    result = svc.create_reservation(
        user_id=current_user,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        direction="sell",
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ReservationResponse(
        success=True,
        message=result["message"],
        data=ReservationItem(**result["data"]) if result["data"] else None,
    )


@router.get("/reservations", response_model=ReservationListResponse)
async def list_reservations(
    current_user: str = Depends(get_current_user),
):
    """
    查询预约单列表（需 JWT 认证）

    返回所有 status='reserved' 的预约单。
    """
    svc = PortfolioService()
    result = svc.list_reservations(user_id=current_user)
    items = [ReservationItem(**item) for item in result["items"]]
    return ReservationListResponse(total=result["total"], items=items)


@router.post("/cancel-reservation/{order_id}", response_model=ReservationResponse)
async def cancel_reservation(
    order_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    取消预约单（需 JWT 认证）

    仅 status='reserved' 的预约单可取消。
    """
    svc = PortfolioService()
    result = svc.cancel_reservation(order_id=order_id, user_id=current_user)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ReservationResponse(
        success=True,
        message=result["message"],
        data=ReservationItem(**result["data"]) if result["data"] else None,
    )


# ==================== 开发测试端点（免 JWT，用 X-User-Id header） ====================


@router.post("/test/buy", response_model=TradeResponse, tags=["portfolio-dev"])
async def test_buy(
    req: TradeRequest,
    user_id: str = Depends(_get_test_user),
):
    """[开发] 买入基金（免 JWT，通过 X-User-Id header 传入用户 ID）"""
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.buy(
        user_id=user_id,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return TradeResponse(
        success=True,
        message=result["message"],
        data=TradeData(**result["data"]) if result["data"] else None,
    )


@router.post("/test/sell", response_model=TradeResponse, tags=["portfolio-dev"])
async def test_sell(
    req: TradeRequest,
    user_id: str = Depends(_get_test_user),
):
    """[开发] 卖出基金（免 JWT，通过 X-User-Id header 传入用户 ID）"""
    svc = PortfolioService()
    price = Decimal(str(req.price)) if req.price is not None else None
    result = svc.sell(
        user_id=user_id,
        fund_code=req.fund_code,
        quantity=Decimal(str(req.quantity)),
        price=price,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return TradeResponse(
        success=True,
        message=result["message"],
        data=TradeData(**result["data"]) if result["data"] else None,
    )


@router.get("/test/positions", response_model=PositionListResponse, tags=["portfolio-dev"])
async def test_list_positions(
    include_quote: bool = Query(True, description="是否按实时行情计算市值和盈亏"),
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
    fund_code: Optional[str] = Query(None, description="基金代码（可选过滤）"),
    direction: Optional[str] = Query(None, description="方向 buy/sell（可选过滤）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
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
    days: int = Query(30, ge=1, le=365, description="查询最近多少天"),
    user_id: str = Depends(_get_test_user),
):
    """[开发] 每日收益率（免 JWT）"""
    svc = PortfolioService()
    result = svc.get_daily_returns(user_id=user_id, days=days)
    items = [DailyReturnItem(**item) for item in result["items"]]
    return DailyReturnResponse(items=items)
