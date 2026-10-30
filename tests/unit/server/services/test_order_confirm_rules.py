"""order_confirm_rules 单元测试：确认链路的纯函数层（不连 DB、不联网）。

对应《订单确认-实现方案》§5.1「份额舍入 / 费用快照 / FIFO / 错误分类」。
金额口径是资金安全的根，这里逐条钉死；多表写的原子性由 SQL 行为用例覆盖。
"""
from datetime import date
from decimal import Decimal

import pytest

from server.services.order_confirm_rules import (
    FEE_SNAPSHOT_FIELDS,
    MONEY_FUND_CODE,
    build_fee_snapshot,
    build_sell_plan,
    calc_buy_amounts,
    classify_rpc_result,
    compute_hold_days,
    nav_for_confirm,
    select_fifo_lots,
)


# ==================== calc_buy_amounts：份额与尾差 ====================

def test_买入确认_份额向下取整_尾差退回现金():
    r = calc_buy_amounts(Decimal("1000.00"), Decimal("1.5000"), Decimal("1.50"))
    assert r["net_amount"] == Decimal("998.50")
    assert r["quantity"] == Decimal("665.66")  # 998.5/1.5 = 665.666...
    assert r["quantity"] * Decimal("1.5000") + r["residual"] == r["net_amount"]


def test_买入确认_金额恒等式_严格相等():
    amount, fee = Decimal("1000.00"), Decimal("0.45")
    r = calc_buy_amounts(amount, Decimal("1.2345"), fee)
    assert r["net_amount"] + r["fee"] == amount


def test_买入确认_尾差极小也不为负():
    r = calc_buy_amounts(Decimal("100.00"), Decimal("3.3333"), Decimal("0"))
    assert r["residual"] >= 0


def test_买入确认_净值非正数抛错():
    with pytest.raises(ValueError):
        calc_buy_amounts(Decimal("100"), Decimal("0"), Decimal("0"))


# ==================== 费用快照 ====================

def test_费用快照_只冻结确认需要的字段():
    rule = {"fund_code": "110020", "confirm_delay": 1, "redeem_settle_delay": 3,
            "updated_at": "2026-10-30T00:00:00Z", "noise": "x"}
    snap = build_fee_snapshot(rule)
    assert set(FEE_SNAPSHOT_FIELDS) <= set(snap)
    assert "fund_code" not in snap and "noise" not in snap
    assert snap["rule_updated_at"] == "2026-10-30T00:00:00Z"


# ==================== 取价与持有期 ====================

def test_确认取价_货基恒为1():
    assert nav_for_confirm(MONEY_FUND_CODE, None) == Decimal("1.0000")
    assert nav_for_confirm("110020", Decimal("1.2345")) == Decimal("1.2345")
    assert nav_for_confirm("110020", None) is None


def test_持有天数_按受理日减批次净值日():
    assert compute_hold_days(date(2026, 10, 30), date(2026, 10, 1)) == 29
    assert compute_hold_days(date(2026, 10, 30), date(2026, 11, 1)) == 0  # 负数按 0


# ==================== FIFO ====================

LOTS = [
    {"id": "l1", "nav_date": "2026-10-01", "available_date": "2026-10-10", "remaining_qty": 100},
    {"id": "l2", "nav_date": "2026-10-20", "available_date": "2026-11-05", "remaining_qty": 50},
    {"id": "l3", "nav_date": "2026-10-25", "available_date": None, "remaining_qty": 30},
]


def test_FIFO_按净值日顺序取用并跳过未到可赎回日():
    picked, gap = select_fifo_lots(LOTS, Decimal("120"), date(2026, 10, 30))
    assert [p["lot_id"] for p in picked] == ["l1", "l3"]
    assert picked[0]["quantity"] == Decimal("100")
    assert picked[1]["quantity"] == Decimal("20")
    assert gap == 0


def test_FIFO_份额不足返回缺口():
    picked, gap = select_fifo_lots(LOTS, Decimal("500"), date(2026, 10, 30))
    assert gap == Decimal("370")
    assert sum(p["quantity"] for p in picked) == Decimal("130")


def test_FIFO_available_date为空回落到净值日():
    lots = [{"id": "l1", "nav_date": "2026-10-01", "available_date": None, "remaining_qty": 10}]
    picked, gap = select_fifo_lots(lots, Decimal("10"), date(2026, 10, 1))
    assert len(picked) == 1 and gap == 0


# ==================== 卖出计划 ====================

def test_卖出计划_逐段计费并汇总():
    segments = [
        {"lot_id": "l1", "quantity": Decimal("100"), "nav_date": date(2026, 10, 1)},
        {"lot_id": "l2", "quantity": Decimal("20"), "nav_date": date(2026, 10, 25)},
    ]
    plan, total = build_sell_plan(
        segments, Decimal("1.5"), date(2026, 10, 30),
        lambda amount, days: 0.0 if days >= 7 else round(amount * 0.015, 2),
    )
    assert plan[0]["hold_days"] == 29 and plan[0]["fee"] == 0.0
    assert plan[1]["hold_days"] == 5 and plan[1]["fee"] == 0.45  # 30 * 1.5 * 1.5%
    assert total == 0.45


def test_卖出计划_费率缺失整体返回None():
    segments = [{"lot_id": "l1", "quantity": Decimal("100"), "nav_date": date(2026, 10, 1)}]
    plan, total = build_sell_plan(segments, Decimal("1.5"), date(2026, 10, 30),
                                  lambda amount, days: None)
    assert plan == [] and total is None


# ==================== 结果分类 ====================

@pytest.mark.parametrize("result,计数", [
    ("completed", "confirmed"),
    ("settling", "confirmed"),
    ("settled", "confirmed"),
    ("rejected", "rejected"),
    ("nav_unavailable", "skipped_nav"),
    ("retryable", "retryable"),
    ("manual_review", "manual_review"),
    ("weird_new_result", "error"),
])
def test_RPC结果映射(result, 计数):
    assert classify_rpc_result({"result": result}) == 计数


def test_RPC结果非字典按error处理():
    assert classify_rpc_result(None) == "error"
