"""backfill_order_confirm 单元测试：日期反推与期初 lot 缺口（纯逻辑，不连库）。

对应《订单确认-实现方案》§3.8.2、§3.15：日期口径错了会算错持有期与到账日，
缺口算法错了会直接打破 `positions.quantity == SUM(lots.remaining_qty)`。
"""
from datetime import date

import pytest

from server.scripts import backfill_order_confirm as bf
from server.services import trading_calendar as tc

RULE = {
    "fund_code": "001594",
    "confirm_delay": 1,
    "redeem_settle_delay": 3,
    "redeem_available_delay": 2,
    "fund_type": "of",
    "share_class": "A",
    "min_purchase_amount": 10,
}


@pytest.fixture(autouse=True)
def 日历():
    # 2026-10-31/11-01 是周末，用来验证跳过非交易日
    days = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]
    tc.install_snapshot(days, coverage_start=date(2026, 9, 1), coverage_end=date(2026, 11, 30))
    yield
    tc.reset_cache()


# ==================== 日期 ====================

def test_买单_受理日按确认日回推确认延迟():
    order = {"direction": "buy", "confirm_date": "2026-10-28"}
    dates = bf.compute_order_dates(order, RULE)
    assert dates == {"accepted_date": "2026-10-27", "available_date": "2026-10-30"}


def test_卖单_受理日等于确认日_到账日顺延():
    order = {"direction": "sell", "confirm_date": "2026-10-28"}
    dates = bf.compute_order_dates(order, RULE)
    assert dates == {"accepted_date": "2026-10-28", "settle_date": "2026-11-02"}


def test_确认延迟为0时_受理日等于确认日():
    order = {"direction": "buy", "confirm_date": "2026-10-28"}
    dates = bf.compute_order_dates(order, {**RULE, "confirm_delay": 0,
                                           "redeem_available_delay": 0})
    assert dates == {"accepted_date": "2026-10-28", "available_date": "2026-10-28"}


def test_缺确认日_拒绝反推():
    with pytest.raises(ValueError):
        bf.compute_order_dates({"direction": "buy", "confirm_date": None}, RULE)


def test_规则缺延迟字段_报错而不是按0算():
    with pytest.raises(KeyError):
        bf.compute_order_dates({"direction": "buy", "confirm_date": "2026-10-28"},
                               {"fund_code": "001594"})


def test_只补缺失字段_不覆盖已有值():
    order = {"direction": "buy", "confirm_date": "2026-10-28",
             "accepted_date": "2026-10-27", "available_date": "2026-10-30",
             "fee_rule_snapshot": {"confirm_delay": 1}, "net_amount": 995.0,
             "amount": 1000, "fee": 5}
    assert bf.build_order_updates(order, RULE) == {}


def test_缺快照与净额时一起补():
    order = {"direction": "buy", "confirm_date": "2026-10-28",
             "accepted_date": "2026-10-27", "available_date": "2026-10-30",
             "fee_rule_snapshot": None, "net_amount": None, "amount": 1000, "fee": 5}
    updates = bf.build_order_updates(order, RULE)
    assert updates["net_amount"] == 995.0
    assert updates["fee_rule_snapshot"]["confirm_delay"] == 1


# ==================== 期初 lot ====================

def _pos(**kw):
    base = {"user_id": "u1", "fund_code": "001594", "fund_name": "测试",
            "quantity": 100, "cost_price": 1.5, "principal": 0,
            "confirm_date": "2026-10-20", "available_date": "2026-10-22"}
    base.update(kw)
    return base


def test_无批次持仓_生成整份期初lot():
    plan = bf.plan_initial_lots([_pos()], [])
    assert len(plan["inserts"]) == 1
    lot = plan["inserts"][0]
    assert lot["quantity"] == 100.0
    assert lot["remaining_cost"] == 150.0
    assert lot["cost_price"] == 1.5
    assert lot["nav_date"] == "2026-10-20"
    assert plan["problems"] == []


def test_已有order批次_只补缺口():
    lots = [{"user_id": "u1", "fund_code": "001594", "source": "order",
             "remaining_qty": 40, "remaining_cost": 60}]
    plan = bf.plan_initial_lots([_pos()], lots)
    assert plan["inserts"][0]["quantity"] == 60.0
    assert plan["inserts"][0]["remaining_cost"] == 90.0


def test_已有期初lot_非重建模式跳过():
    lots = [{"user_id": "u1", "fund_code": "001594", "source": "initial",
             "remaining_qty": 100, "remaining_cost": 150}]
    plan = bf.plan_initial_lots([_pos()], lots)
    assert plan["inserts"] == [] and plan["deletes"] == []


def test_重建模式_删除旧期初lot并按缺口重建():
    lots = [{"user_id": "u1", "fund_code": "001594", "source": "initial",
             "remaining_qty": 100, "remaining_cost": 150}]
    plan = bf.plan_initial_lots([_pos(quantity=120)], lots, rebuild=True)
    assert plan["deletes"] == [("u1", "001594")]
    assert plan["inserts"][0]["quantity"] == 120.0


def test_批次份额超过持仓_报问题不写入():
    lots = [{"user_id": "u1", "fund_code": "001594", "source": "order",
             "remaining_qty": 130, "remaining_cost": 195}]
    plan = bf.plan_initial_lots([_pos()], lots, rebuild=True)
    assert plan["inserts"] == []
    assert plan["problems"][0]["kind"] == "lot_exceeds_position"


def test_货基本金缺失_按份额兜底并告警():
    pos = _pos(fund_code="000198", quantity=500, principal=0, cost_price=1.0)
    plan = bf.plan_initial_lots([pos], [])
    assert plan["inserts"][0]["remaining_cost"] == 500.0
    assert "本金" in plan["inserts"][0]["_note"]


def test_货基本金优先于成本价():
    pos = _pos(fund_code="000198", quantity=500, principal=480, cost_price=1.0)
    plan = bf.plan_initial_lots([pos], [])
    assert plan["inserts"][0]["remaining_cost"] == 480.0


def test_零份额持仓不生成lot():
    assert bf.plan_initial_lots([_pos(quantity=0)], [])["inserts"] == []
