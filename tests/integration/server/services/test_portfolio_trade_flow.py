"""P0-2 交易链路集成测试：PortfolioService ↔ 真实 Postgres（多表一致性）。

模块名称：场外基金持仓交易服务
所测功能：申购冻结→确认解冻建仓→赎回扣仓入账，跨 accounts/positions/trade_orders/trade_flow 四表
使用的测试方法：本地 Supabase 栈 + 真实费率种子 + 合成 user_id + 分阶段冻结时钟 + mock 净值读取（FundNavService 隔离）

注：apply_purchase 写订单时 price=0（pending 阶段），确认时读「确认日」净值（只读 DB）。
本测试聚焦多表资金流转，故把 `_latest_nav` / `_confirm_nav` 打成固定净值；
净值读不到时的语义（订单**保持 pending**、冻结不释放）由
test_确认时净值不可用_订单保持pending且冻结不释放 单独验证。
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

BEIJING = timezone(timedelta(hours=8))
# 提交日：2026-09-14 周一 14:00（盘中、15:00 截止前）
SUBMIT_DAY = datetime(2026, 9, 14, 14, 0, tzinfo=BEIJING)
# 确认日：2026-09-15 周二（T+1，confirm_delay=1）
CONFIRM_DAY = datetime(2026, 9, 15, 14, 0, tzinfo=BEIJING)
NAV = Decimal("1.5")


def _travel(day):
    import time_machine

    return time_machine.travel(day)


@pytest.fixture
def trade_service(portfolio_service, monkeypatch):
    """隔离净值读取服务：固定净值 1.5（货基恒 1.0000）。"""
    def _固定净值(fund_code):
        return Decimal("1.0000") if fund_code == "000198" else NAV

    monkeypatch.setattr(portfolio_service, "_latest_nav", _固定净值)
    monkeypatch.setattr(
        portfolio_service,
        "_confirm_nav",
        lambda order: _固定净值(order["fund_code"]),
    )
    return portfolio_service


def test_申购_冻结资金并写pending订单(trade_service, supabase_client, user_id):
    with _travel(SUBMIT_DAY):
        r = trade_service.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))
    assert r["success"] is True
    assert r["data"]["status"] == "pending"

    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    assert Decimal(str(acct["cash"])) == Decimal("99000")  # 100000 - 1000
    assert Decimal(str(acct["frozen_cash"])) == Decimal("1000")

    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert len(orders) == 1
    assert orders[0]["status"] == "pending"
    assert orders[0]["direction"] == "buy"
    assert orders[0]["fund_code"] == "110020"


def test_确认_解冻建仓写流水(trade_service, supabase_client, user_id):
    with _travel(SUBMIT_DAY):
        trade_service.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))
    with _travel(CONFIRM_DAY):
        r = trade_service.confirm_pending_orders()
    assert r["status"] == "ok"
    assert r["processed"] == 1

    # 解冻：frozen_cash 归零
    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    assert Decimal(str(acct["frozen_cash"])) == Decimal("0")

    # 建仓：positions 1 条，份额 > 0
    positions = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data
    assert len(positions) == 1
    assert Decimal(str(positions[0]["quantity"])) > 0

    # 流水：trade_flow 1 条 buy
    flows = supabase_client.table("trade_flow").select("*").eq("user_id", user_id).execute().data
    assert len(flows) == 1
    assert flows[0]["direction"] == "buy"

    # 订单 completed
    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert orders[0]["status"] == "completed"


def test_申购确认_资金守恒(trade_service, supabase_client, user_id):
    """申购 1000 元并确认后：现金 + 冻结 + 持仓市值 = 100000 - 申购费。"""
    with _travel(SUBMIT_DAY):
        trade_service.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))
    with _travel(CONFIRM_DAY):
        trade_service.confirm_pending_orders()

    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    cash = Decimal(str(acct["cash"]))
    frozen = Decimal(str(acct["frozen_cash"]))

    pos = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data[0]
    qty = Decimal(str(pos["quantity"]))
    market_value = (qty * NAV).quantize(Decimal("0.01"))

    total = cash + frozen + market_value
    # 初始 100000，减去申购费（110020 第一档 0.0012，外扣法约 1.20 元）
    assert float(total) == pytest.approx(float(Decimal("100000") - Decimal("1.20")), abs=0.05)


def test_赎回_持仓清空现金入账(trade_service, supabase_client, user_id):
    # 申购 + 确认（持有从确认日 09-15 起算）
    with _travel(SUBMIT_DAY):
        trade_service.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))
    with _travel(CONFIRM_DAY):
        trade_service.confirm_pending_orders()
        pos = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data[0]
        qty = Decimal(str(pos["quantity"]))
        cash_before = Decimal(str(
            supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]["cash"]
        ))

        # 赎回全部份额（持有 0 天 → 命中 1.5% 赎回费）
        r = trade_service.apply_redeem(user_id, "110020", qty, price=Decimal("1.5"))
        assert r["success"] is True
        trade_service.confirm_pending_orders()

    # 持仓清空
    positions = supabase_client.table("positions").select("*").eq("user_id", user_id).eq("fund_code", "110020").execute().data
    assert len(positions) == 0

    # 现金入账（赎回净额 = 份额×1.5 - 1.5% 赎回费）
    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    assert Decimal(str(acct["cash"])) > cash_before


def test_确认时净值不可用_订单保持pending且冻结不释放(
    trade_service, supabase_client, user_id, monkeypatch
):
    """确认日净值还没到（NOT_YET_PUBLISHED / FETCH_FAILED / NO_NAV）→ 保持 pending。

    端到端验证三件事，缺一都会造成资金问题：
    1. 订单仍是 pending（可以下一轮继续确认，不是被拒单）；
    2. 冻结资金原样保留（一旦解冻，下一轮再确认会二次解冻，扣到同账户其他挂单的冻结额）；
    3. 未建仓、未写流水。
    """
    from server.services.portfolio_service import NavUnavailableForConfirm

    with _travel(SUBMIT_DAY):
        trade_service.apply_purchase(user_id, "110020", Decimal("1000"), price=Decimal("1.5"))

    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    cash_after_order = Decimal(str(acct["cash"]))          # 100000 - 1000
    assert Decimal(str(acct["frozen_cash"])) == Decimal("1000")

    def _净值未到(order):
        raise NavUnavailableForConfirm(order["id"], "2026-09-15", "not_yet_published")

    monkeypatch.setattr(trade_service, "_confirm_nav", _净值未到)
    with _travel(CONFIRM_DAY):
        r = trade_service.confirm_pending_orders()
    assert r["processed"] == 1
    assert r["skipped"] == 1
    assert r["confirmed"] == 0

    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert orders[0]["status"] == "pending"

    # 资金未动：现金与冻结都保持下单后的状态
    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    assert Decimal(str(acct["cash"])) == cash_after_order
    assert Decimal(str(acct["frozen_cash"])) == Decimal("1000")

    # 未建仓、未写流水
    assert supabase_client.table("positions").select("*").eq("user_id", user_id).execute().data == []
    assert supabase_client.table("trade_flow").select("*").eq("user_id", user_id).execute().data == []


def test_查不到规则_拒绝交易(trade_service, user_id):
    with _travel(SUBMIT_DAY):
        r = trade_service.apply_purchase(user_id, "999999", Decimal("1000"), price=Decimal("1.0"))
    assert r["success"] is False
    assert "不支持" in r["message"]
