"""存量订单回填：确认所需的日期字段、费率快照、净额与期初 lot。

用法::

    poetry run python -m server.scripts.backfill_order_confirm             # dry-run（默认）
    poetry run python -m server.scripts.backfill_order_confirm --apply     # 真正写库
    poetry run python -m server.scripts.backfill_order_confirm --rebuild-lots --apply

设计来源：《订单确认-实现方案》§3.8.2、§3.15。要点：

- **默认只读**：不加 `--apply` 不写任何数据，只打印计划与数据质量问题。
- **幂等**：只补 `NULL` 字段；期初 lot 按「持仓份额 − 非期初 lot 份额」的缺口生成，
  重复执行不会重复插入。
- **不猜**：缺 `confirm_date`、基金无规则、日期超出交易日历覆盖区间的订单一律列出
  并计入退出码，不写半套数据（这类单确认时会转 `manual_review`）。
- **顺序**：先写期初 lot、再写订单日期字段 —— 中途失败时订单仍缺 `accepted_date`，
  Runner 只会转人工，不会在 lot 不全的情况下扣份额。

退出码：0 = 无问题；1 = 有问题（数据质量或无法反推），此时 `--apply` 也不会写这一类。
"""
import argparse
import json
import logging
import os
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

# 环境变量必须在导入 server.* 之前加载（一次性脚本不会走 server/app.py 的启动流程）
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

from server.services.order_confirm_rules import (  # noqa: E402
    MONEY_FUND_CODE,
    build_fee_snapshot,
)
from server.services.trading_calendar import (  # noqa: E402
    CalendarOutOfCoverage,
    CalendarUnavailable,
    load_calendar_cache,
    next_trading_day,
    prev_trading_day,
)
from server.storage.supabase_client import get_supabase  # noqa: E402

logger = logging.getLogger("backfill_order_confirm")

# 需要回填的订单状态：旧代码只有 pending，manual_review 是人工重排前的同一类单
PENDING_STATUSES = ("pending", "manual_review")
CHANGE_EPS = Decimal("0.01")


# ==================== 纯逻辑：订单日期 ====================


def compute_order_dates(order: dict, rule: dict) -> dict:
    """按设计 §3.15 由 `confirm_date` 反推/顺延出缺失的日期字段。

    买单：受理日 = 确认日回推 `confirm_delay` 个交易日；可赎回日 = 确认日顺延
        `redeem_available_delay` 个交易日。
    卖单：受理日 = 确认日（旧口径卖单确认日即净值日）；到账日 = 确认日顺延
        `redeem_settle_delay` 个交易日。

    日历越界/未载入时抛 `CalendarOutOfCoverage` / `CalendarUnavailable`，
    由调用方记为「无法反推」，不做工作日兜底。
    """
    confirm = _as_date(order.get("confirm_date"))
    if confirm is None:
        raise ValueError("订单缺少 confirm_date")

    if order.get("direction") == "buy":
        accepted = confirm
        for _ in range(_require_delay(rule, "confirm_delay")):
            accepted = prev_trading_day(accepted)
        available = confirm
        for _ in range(_require_delay(rule, "redeem_available_delay")):
            available = next_trading_day(available)
        return {"accepted_date": accepted.isoformat(),
                "available_date": available.isoformat()}

    settle = confirm
    for _ in range(_require_delay(rule, "redeem_settle_delay")):
        settle = next_trading_day(settle)
    return {"accepted_date": confirm.isoformat(),
            "settle_date": settle.isoformat()}


def build_order_updates(order: dict, rule: dict) -> dict:
    """算出该订单需要写回的字段；已存在的字段不动（幂等，也不覆盖新代码写过的值）。"""
    updates: dict = {}

    if order.get("fee_rule_snapshot") is None:
        updates["fee_rule_snapshot"] = build_fee_snapshot(rule)
    if order.get("direction") == "buy" and order.get("net_amount") is None:
        amount = _dec(order.get("amount"))
        fee = _dec(order.get("fee"))
        updates["net_amount"] = float(amount - fee)

    missing_dates = False
    if order.get("direction") == "buy":
        missing_dates = order.get("accepted_date") is None or order.get("available_date") is None
    else:
        missing_dates = order.get("accepted_date") is None or order.get("settle_date") is None
    if missing_dates:
        updates.update(compute_order_dates(order, rule))
    return updates


# ==================== 纯逻辑：期初 lot ====================


def plan_initial_lots(positions: Iterable[dict], lot_rows: Iterable[dict],
                      rebuild: bool = False) -> dict:
    """按「持仓 − 非期初 lot」的缺口生成期初 lot。

    为什么用缺口而不是持仓全量：灰度前可能有部分订单已按新代码确认并写了 `order` lot，
    按全量插入会重复计份额，直接破坏 `positions.quantity == SUM(lots.remaining_qty)`。

    返回 `{"inserts": [...], "deletes": [(user, fund)], "problems": [...]}`；
    `rebuild=True` 时连已有期初 lot 一起重算（回滚演练用，不动 `order`/`income` lot）。
    """
    agg: dict[tuple, dict] = {}
    for lot in lot_rows:
        key = (str(lot.get("user_id")), lot.get("fund_code"))
        bucket = agg.setdefault(key, {"qty": Decimal("0"), "cost": Decimal("0"),
                                      "has_initial": False})
        if lot.get("source") == "initial":
            bucket["has_initial"] = True
            continue
        bucket["qty"] += _dec(lot.get("remaining_qty"))
        bucket["cost"] += _dec(lot.get("remaining_cost"))

    inserts: list[dict] = []
    deletes: list[tuple] = []
    problems: list[dict] = []

    for pos in positions:
        quantity = _dec(pos.get("quantity"))
        if quantity <= 0:
            continue
        user_id, fund_code = str(pos.get("user_id")), pos.get("fund_code")
        key = (user_id, fund_code)
        bucket = agg.get(key, {"qty": Decimal("0"), "cost": Decimal("0"),
                               "has_initial": False})

        has_initial = bucket["has_initial"]
        if has_initial and not rebuild:
            continue

        target_cost, note = _position_cost(pos, quantity)
        gap_qty = quantity - bucket["qty"]
        gap_cost = target_cost - bucket["cost"]

        if has_initial:
            # rebuild：先清掉旧期初 lot，再按缺口重建
            deletes.append(key)
        if abs(gap_qty) < CHANGE_EPS:
            continue
        if gap_qty < 0:
            problems.append({"kind": "lot_exceeds_position", "user_id": user_id,
                             "fund_code": fund_code, "position_quantity": str(quantity),
                             "lot_quantity": str(bucket["qty"]),
                             "message": "非期初 lot 份额已超过持仓，回填会破坏不变量，请人工核对"})
            continue
        if gap_cost < 0:
            problems.append({"kind": "lot_cost_exceeds_position", "user_id": user_id,
                             "fund_code": fund_code, "target_cost": str(target_cost),
                             "lot_cost": str(bucket["cost"]),
                             "message": "非期初 lot 成本已超过持仓成本，请人工核对"})
            continue

        inserts.append({
            "user_id": user_id,
            "fund_code": fund_code,
            "fund_name": pos.get("fund_name") or "",
            "source": "initial",
            "source_ref": "initial",
            "nav_date": _lot_nav_date(pos).isoformat(),
            "available_date": _lot_available_date(pos).isoformat(),
            "quantity": float(gap_qty),
            "remaining_qty": float(gap_qty),
            "cost_price": _lot_cost_price(gap_qty, gap_cost),
            "remaining_cost": float(gap_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "_note": note,
        })
    return {"inserts": inserts, "deletes": deletes, "problems": problems}


def _position_cost(pos: dict, quantity: Decimal) -> tuple[Decimal, Optional[str]]:
    """持仓的「应有总成本」。货基用本金；普通基金用 份额 × 成本均价。

    本金缺失（货基 principal=0）或成本价为 0 时按设计 §3.8.2 兜底并给出告警说明，
    但只记录在 `_note` 里，由人工确认——不静默当正常数据。
    """
    if pos.get("fund_code") == MONEY_FUND_CODE:
        principal = _dec(pos.get("principal"))
        if principal <= 0:
            return quantity, "货基本金 principal 缺失，已按份额兜底，需人工确认"
        return principal, None
    cost_price = _dec(pos.get("cost_price"))
    if cost_price <= 0:
        return Decimal("0"), "普通基金 cost_price 为 0，期初 lot 成本记 0，卖出盈亏会虚高"
    return (quantity * cost_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), None


def _lot_nav_date(pos: dict) -> date:
    return (_as_date(pos.get("confirm_date")) or _as_date(pos.get("created_at"))
            or date.today())


def _lot_available_date(pos: dict) -> date:
    return (_as_date(pos.get("available_date")) or _as_date(pos.get("confirm_date"))
            or _as_date(pos.get("created_at")) or date.today())


def _lot_cost_price(quantity: Decimal, cost: Decimal) -> float:
    if quantity <= 0:
        return 0.0
    return float((cost / quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ==================== 数据读取 ====================


def _fetch_pending_orders(client) -> list[dict]:
    rows: list[dict] = []
    page = 1000
    offset = 0
    while True:
        batch = (client.table("trade_orders")
                 .select("*")
                 .in_("status", list(PENDING_STATUSES))
                 .order("id")
                 .range(offset, offset + page - 1)
                 .execute()).data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


def _fetch_rules(client, codes: set[str]) -> dict[str, dict]:
    if not codes:
        return {}
    rows = (client.table("fund_trade_rule")
            .select("*")
            .in_("fund_code", sorted(codes))
            .execute()).data or []
    return {row["fund_code"]: row for row in rows}


def _fetch_all(client, table: str) -> list[dict]:
    rows: list[dict] = []
    page = 1000
    offset = 0
    while True:
        batch = (client.table(table).select("*").order("id")
                 .range(offset, offset + page - 1).execute()).data or []
        rows.extend(batch)
        if len(batch) < page:
            return rows
        offset += page


# ==================== 执行 ====================


def run(apply: bool, rebuild_lots: bool) -> dict:
    client = get_supabase()
    if client is None:
        raise RuntimeError("Supabase 客户端不可用（检查 SUPABASE_URL / SERVICE_ROLE_KEY）")

    # 日历只能从 DB 快照载入；没载入就别往下算，避免用错误日期回填
    if not load_calendar_cache():
        raise RuntimeError("交易日历未载入（trading_calendar 为空或读取失败），中止回填")

    orders = _fetch_pending_orders(client)
    rules = _fetch_rules(client, {o.get("fund_code") for o in orders})

    order_plan: list[dict] = []
    unresolvable: list[dict] = []
    for order in orders:
        rule = rules.get(order.get("fund_code"))
        if rule is None:
            unresolvable.append({"kind": "rule_missing", "order_id": order.get("id"),
                                 "fund_code": order.get("fund_code"),
                                 "message": "fund_trade_rule 中无该基金，无法生成费率快照与日期"})
            continue
        try:
            updates = build_order_updates(order, rule)
        except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
            unresolvable.append({"kind": "calendar", "order_id": order.get("id"),
                                 "fund_code": order.get("fund_code"),
                                 "message": str(exc)})
            continue
        except (ValueError, KeyError, TypeError) as exc:
            unresolvable.append({"kind": "invalid_order", "order_id": order.get("id"),
                                 "fund_code": order.get("fund_code"),
                                 "message": str(exc)})
            continue
        if updates:
            order_plan.append({"order_id": order.get("id"),
                               "direction": order.get("direction"),
                               "fund_code": order.get("fund_code"),
                               "updates": updates})

    positions = _fetch_all(client, "positions")
    lots = _fetch_all(client, "position_lots")
    lot_plan = plan_initial_lots(positions, lots, rebuild=rebuild_lots)

    report = {
        "mode": "apply" if apply else "dry-run",
        "rebuild_lots": rebuild_lots,
        "orders_scanned": len(orders),
        "orders_to_update": len(order_plan),
        "lots_to_insert": len(lot_plan["inserts"]),
        "lots_to_delete": len(lot_plan["deletes"]),
        "unresolvable": unresolvable,
        "lot_problems": lot_plan["problems"],
        "lot_warnings": [i["_note"] for i in lot_plan["inserts"] if i.get("_note")],
        "sample_orders": order_plan[:10],
        "sample_lots": [{k: v for k, v in i.items() if not k.startswith("_")}
                        for i in lot_plan["inserts"][:10]],
    }

    if apply:
        report["written"] = _apply(client, lot_plan, order_plan)

    problems = len(unresolvable) + len(lot_plan["problems"])
    report["problems"] = problems
    return report


def _apply(client, lot_plan: dict, order_plan: list[dict]) -> dict:
    """先 lot 后订单：订单日期缺失时 Runner 只会转人工，不会在 lot 不全时扣份额。"""
    deleted = 0
    for user_id, fund_code in lot_plan["deletes"]:
        (client.table("position_lots").delete()
         .eq("user_id", user_id).eq("fund_code", fund_code).eq("source", "initial")
         .execute())
        deleted += 1

    inserted = 0
    for row in lot_plan["inserts"]:
        client.table("position_lots").insert(
            {k: v for k, v in row.items() if not k.startswith("_")}
        ).execute()
        inserted += 1
    logger.info("[回填] 期初 lot：删除 %s 组、插入 %s 条", deleted, inserted)

    updated = 0
    for item in order_plan:
        (client.table("trade_orders").update(item["updates"])
         .eq("id", item["order_id"]).execute())
        updated += 1
    logger.info("[回填] 订单字段更新 %s 笔", updated)
    return {"lots_deleted": deleted, "lots_inserted": inserted, "orders_updated": updated}


# ==================== 工具 ====================


def _dec(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _require_delay(rule: dict, field: str) -> int:
    value = rule.get(field)
    if value is None:
        raise KeyError(f"资金规则缺少 {field}")
    delay = int(value)
    if delay < 0:
        raise ValueError(f"{field} 为负数：{delay}")
    return delay


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="存量订单确认字段回填（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正写库；不加只打印计划")
    parser.add_argument("--rebuild-lots", action="store_true",
                        help="重算期初 lot（回滚演练用，不动 order/income lot）")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = run(apply=args.apply, rebuild_lots=args.rebuild_lots)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
