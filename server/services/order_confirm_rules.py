"""订单确认的纯函数层：费用快照、份额舍入、持有期、FIFO 计划、结果分类。

**本模块不连接数据库、不发网络请求**，所有输入都由调用方取好传进来，
这样金额口径可以被单元测试逐条钉死（见《实现方案》§3.7、§5.1）。

设计口径（改动前先看文档）：
- 成交净值日 = `trade_orders.accepted_date`（受理日 T），`confirm_date` 只决定份额何时到账；
- 买入 `net = amount - fee`（严格相等），`qty = floor(net / nav, 2)`，`residual = net - qty*nav`；
- 卖出按 lot 分段计费，`hold_days = accepted_date - lot.nav_date`，成本由 RPC 在锁内重算。
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Callable, Iterable, Optional

# 货基：净值恒 1.0000，成本价恒 1.0000，本金（principal）单独记账
MONEY_FUND_CODE = "000198"

# 费用快照里需要冻结的字段（键名与 fund_catalog 一致，
# 确认时可把快照直接当 rule 传给 FundFeeService）
FEE_SNAPSHOT_FIELDS = (
    "fund_type",
    "share_class",
    "subscribe_status",
    "confirm_delay",
    "redeem_settle_delay",
    "redeem_available_delay",
    "min_purchase_amount",
    "max_purchase_amount",
    "purchase_fee_tiers",
    "redemption_fee_tiers",
    "management_fee_rate",
    "custody_fee_rate",
    "sales_service_fee_rate",
)

# RPC 结果 → 计数器名（《执行机制》§3.5.2 的映射表）
RPC_RESULT_COUNTER = {
    "completed": "confirmed",
    "settling": "confirmed",
    "settled": "confirmed",
    "rejected": "rejected",
    "nav_unavailable": "skipped_nav",
    "retryable": "retryable",
    "manual_review": "manual_review",
}


def build_fee_snapshot(rule: dict) -> dict:
    """从 fund_catalog 行生成下单快照。

    只冻结「确认时需要」的字段；`rule_updated_at` 仅用于溯源，不参与计算。
    快照缺失即人工处理（`FEE_SNAPSHOT_MISSING`），不做费率兜底。
    """
    snapshot = {k: rule.get(k) for k in FEE_SNAPSHOT_FIELDS}
    snapshot["rule_updated_at"] = rule.get("updated_at")
    return snapshot


def calc_buy_amounts(amount: Decimal, nav: Decimal, fee: Decimal) -> dict:
    """买入确认的金额与份额。

    `net = amount - fee` 必须严格相等（不再单独 round net，否则
    `amount == net + fee` 会差 0.01）；份额向下取整保证 `residual >= 0`。
    """
    if nav is None or nav <= 0:
        raise ValueError(f"净值必须为正数，实际 {nav}")
    net = amount - fee
    quantity = (net / nav).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    residual = (net - quantity * nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if residual < 0:  # 舍入极端情况下防御性清零，保证不会从现金倒扣
        residual = Decimal("0.00")
    return {
        "fee": fee,
        "net_amount": net,
        "quantity": quantity,
        "residual": residual,
    }


def nav_for_confirm(fund_code: str, lookup_nav: Optional[Decimal]) -> Optional[Decimal]:
    """确认取价：货基恒 1.0000，其余用调用方读到的 T 日净值。"""
    if fund_code == MONEY_FUND_CODE:
        return Decimal("1.0000")
    return lookup_nav


def compute_hold_days(accepted_date: date, lot_nav_date: date) -> int:
    """持有天数 = 卖出受理日 - 该批次的成交净值日；负数按 0（数据异常偏保守）。"""
    if not accepted_date or not lot_nav_date:
        return 0
    return max((accepted_date - lot_nav_date).days, 0)


def select_fifo_lots(lots: Iterable[dict], quantity: Decimal,
                     accepted_date: date) -> tuple[list[dict], Decimal]:
    """按 FIFO 从 lots 里取够 `quantity`，返回 (分段, 缺口)。

    - `lots` 必须已按 `(nav_date, created_at, id)` 升序排好（DB 侧排序）；
    - 只取 `COALESCE(available_date, nav_date) <= accepted_date` 的批次；
    - 计划是乐观的：RPC 会 `FOR UPDATE` 重新校验，被并发卖出时返回 `LOT_PLAN_STALE`。
    """
    remaining = Decimal(str(quantity))
    picked: list[dict] = []

    for lot in lots:
        if remaining <= 0:
            break
        available = _as_date(lot.get("available_date")) or _as_date(lot.get("nav_date"))
        if available and available > accepted_date:
            continue
        lot_qty = Decimal(str(lot.get("remaining_qty") or 0))
        if lot_qty <= 0:
            continue
        take = lot_qty if lot_qty < remaining else remaining
        picked.append({
            "lot_id": str(lot["id"]),
            "quantity": take,
            "nav_date": _as_date(lot.get("nav_date")),
        })
        remaining -= take

    return picked, remaining if remaining > 0 else Decimal("0")


def build_sell_plan(segments: list[dict], nav: Decimal, accepted_date: date,
                    redeem_fee: Callable[[float, int], Optional[float]]) -> tuple[list[dict], Optional[float]]:
    """给 FIFO 分段补上费用与持有天数，返回 (p_plan, 总费用)。

    `redeem_fee(金额, 持有天数)` 返回该段赎回费；返回 None 表示费率规则缺失，
    此时整体返回 `(分段, None)`，由调用方转人工，绝不按免赎回费放行。
    """
    plan: list[dict] = []
    total_fee = 0.0
    for seg in segments:
        amount = (seg["quantity"] * nav).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        hold_days = compute_hold_days(accepted_date, seg["nav_date"])
        fee = redeem_fee(float(amount), hold_days)
        if fee is None:
            return plan, None
        total_fee += float(fee)
        plan.append({
            "lot_id": seg["lot_id"],
            "quantity": float(seg["quantity"]),
            "fee": float(fee),
            "hold_days": hold_days,
        })
    return plan, round(total_fee, 2)


def classify_rpc_result(payload) -> str:
    """把 RPC 返回的 jsonb 映射成计数器名；未知结果按 `error` 处理。"""
    if not isinstance(payload, dict):
        return "error"
    return RPC_RESULT_COUNTER.get(payload.get("result"), "error")


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
