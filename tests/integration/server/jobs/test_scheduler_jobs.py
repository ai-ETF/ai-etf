"""P1-7 调度任务集成测试：任务函数直调 → PortfolioService → 真实 Postgres。

模块名称：APScheduler 定时任务
所测功能：确认任务 / 启动补偿任务直调后，pending 订单 → completed + 持仓建仓的真实 DB 流转
使用的测试方法：本地 Supabase 栈 + 合成 user_id + 冻结时钟 + mock _get_nav（类级）
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

BEIJING = timezone(timedelta(hours=8))
SUBMIT_DAY = datetime(2026, 9, 14, 14, 0, tzinfo=BEIJING)
CONFIRM_DAY = datetime(2026, 9, 15, 14, 0, tzinfo=BEIJING)


@pytest.fixture
def trade_env(portfolio_service, monkeypatch):
    """类级 mock _get_nav，使任务函数内部新建的 PortfolioService 也返回固定净值。"""
    from server.services.portfolio_service import PortfolioService

    monkeypatch.setattr(
        PortfolioService,
        "_get_nav",
        lambda self, fc: Decimal("1.0000") if fc == "000198" else Decimal("1.5"),
    )
    return portfolio_service


def _travel(day):
    import time_machine

    return time_machine.travel(day)


def test_确认任务_确认pending订单并建仓(trade_env, supabase_client, user_id):
    from server.services.spot_cache_scheduler import _confirm_pending_orders_job

    with _travel(SUBMIT_DAY):
        trade_env.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))

    # 确认日直调任务函数
    with _travel(CONFIRM_DAY):
        asyncio.run(_confirm_pending_orders_job())

    # 订单 completed + 持仓建仓
    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert orders[0]["status"] == "completed"
    positions = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data
    assert len(positions) == 1
    assert Decimal(str(positions[0]["quantity"])) > 0


def test_启动补偿_确认遗漏订单(trade_env, supabase_client, user_id):
    from server.services.spot_cache_scheduler import _startup_pending_compensation

    with _travel(SUBMIT_DAY):
        trade_env.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))

    # 启动补偿 skip_trading_day_check=True，但仍要求 confirm_date <= today，
    # 故时钟推进到确认日 09-15（订单 confirm_date 也是 09-15）
    with _travel(CONFIRM_DAY):
        asyncio.run(_startup_pending_compensation())

    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert orders[0]["status"] == "completed"
    positions = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data
    assert len(positions) == 1


def test_无pending订单_确认任务不处理(trade_env, user_id):
    from server.services.spot_cache_scheduler import _confirm_pending_orders_job

    with _travel(CONFIRM_DAY):
        asyncio.run(_confirm_pending_orders_job())
    # 无异常即通过（processed=0 场景）
