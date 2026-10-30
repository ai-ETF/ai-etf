"""订单确认 Runner（编排层）。

职责（见《订单确认-执行机制》§3.5）：拿批次锁 → 回收过期租约 → keyset 扫描到期订单
→ 逐单取净值、算金额、调用写 RPC → 到账 → 写批次审计。

边界：
- **编排在这里，记账在数据库**。所有资金/持仓/流水写入都走 `confirm_*` RPC，
  本模块不改 `accounts`/`positions`/`position_lots`/`trade_flow`。
- 取价日 = `accepted_date`（受理日 T），`confirm_date` 只是扫描门槛。
- 预期内业务失败：RPC 返回 `{result:...}`，这里只做映射与计数，不补偿。
- 连接级异常：中止本轮并 `finish_confirm_run(failed)`，订单保持原状态等下一轮。
"""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from server.config.settings import SETTINGS
from server.services.order_confirm_rules import (
    MONEY_FUND_CODE,
    build_sell_plan,
    calc_buy_amounts,
    classify_rpc_result,
    select_fifo_lots,
)
from server.services.trading_calendar import beijing_now

logger = logging.getLogger(__name__)

COUNTER_KEYS = (
    "scanned", "confirmed", "rejected",
    "skipped_nav", "retryable", "manual_review", "settled",
)

# 连接级故障：本轮必须中止，订单保持原状态（下一轮重试），不能算单笔失败
_CONNECTION_ERROR_TYPES = (
    "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout",
    "PoolTimeout", "RemoteProtocolError", "NetworkError",
)


class OrderConfirmService:
    """单轮订单确认的编排器。可注入 client / 净值服务 / 费率服务，便于测试。"""

    def __init__(self, client=None, nav_service=None, fee_service=None):
        self._client = client
        self._nav_service = nav_service
        self._fee_service = fee_service
        self._nav_cache: dict[tuple[str, date], tuple[str, Optional[Decimal]]] = {}

    # ==================== 依赖（懒加载，避免导入即连库） ====================

    @property
    def client(self):
        if self._client is None:
            from server.storage.supabase_client import get_supabase
            self._client = get_supabase()
        return self._client

    @property
    def nav(self):
        if self._nav_service is None:
            from server.services.fund_nav_service import FundNavService
            self._nav_service = FundNavService()
        return self._nav_service

    @property
    def fee(self):
        if self._fee_service is None:
            from server.services.fund_fee_service import FundFeeService
            self._fee_service = FundFeeService()
        return self._fee_service

    @property
    def worker_id(self) -> str:
        return f"{socket.gethostname()}:{os.getpid()}"

    # ==================== 入口 ====================

    def run(self, trigger: str = "manual", today: Optional[date] = None) -> dict:
        """跑一轮确认。`trigger` 取 sync / fallback / startup / manual。

        返回与 `confirm_runs` 一致的计数；拿不到批次锁返回 `status='busy'`。
        """
        today = today or beijing_now().date()
        worker = self.worker_id
        counters = {k: 0 for k in COUNTER_KEYS}

        run_id = self._rpc("acquire_confirm_run", {
            "p_trigger": trigger,
            "p_worker": worker,
        })
        if not run_id:
            logger.info("[确认] 已有批次在跑，本轮跳过 trigger=%s worker=%s", trigger, worker)
            return self._result("busy", None, counters, today, trigger, "已有批次在跑")

        started = time.monotonic()
        error: Optional[str] = None
        truncated = False
        try:
            self._reap_stale()
            truncated = self._scan_loop(run_id, worker, today, counters, started)
            counters["settled"] += self._settle_due(worker, today)
        except Exception as exc:  # 连接级/未预期：中止本轮，订单保持原状态
            error = f"{type(exc).__name__}: {exc}"
            logger.error("[确认] 本轮中止: %s", error, exc_info=True)
            try:
                self._finish(run_id, "failed", counters, error)
            except Exception:
                logger.exception("[确认] 写批次失败状态也失败 run_id=%s", run_id)
            raise
        else:
            self._finish(run_id, "succeeded", counters,
                         "time_budget_exceeded" if truncated else None)

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "[确认] run_id=%s trigger=%s worker=%s scanned=%s confirmed=%s rejected=%s "
            "skipped_nav=%s retryable=%s manual_review=%s settled=%s duration_ms=%s%s",
            run_id, trigger, worker, counters["scanned"], counters["confirmed"],
            counters["rejected"], counters["skipped_nav"], counters["retryable"],
            counters["manual_review"], counters["settled"], duration_ms,
            " truncated" if truncated else "",
        )
        return self._result("ok", run_id, counters, today, trigger,
                            "time_budget_exceeded" if truncated else None,
                            duration_ms)

    # ==================== 扫描 ====================

    def _scan_loop(self, run_id: str, worker: str, today: date,
                   counters: dict, started: float) -> bool:
        """keyset 分页扫描，返回是否因超限/超时提前结束。"""
        cursor: Optional[tuple[str, str]] = None
        while True:
            if counters["scanned"] >= SETTINGS.CONFIRM_MAX_ORDERS:
                return True
            if time.monotonic() - started > SETTINGS.CONFIRM_TIME_BUDGET_SECONDS:
                return True

            page = self._scan_page(cursor, today)
            if not page:
                return False

            for order in page:
                counters["scanned"] += 1
                outcome = self._process(order, today, worker, counters)
                if outcome in counters and outcome != "scanned":
                    counters[outcome] += 1

            self._rpc("heartbeat_confirm_run", {"p_run_id": run_id})

            if len(page) < SETTINGS.CONFIRM_PAGE_SIZE:
                return False
            last = page[-1]
            cursor = (str(last.get("confirm_date"))[:10], str(last.get("id")))

    def _scan_page(self, cursor: Optional[tuple[str, str]], today: date) -> list[dict]:
        query = (
            self.client.table("trade_orders")
            .select("*")
            .eq("status", "pending")
            .lte("confirm_date", today.isoformat())
            .order("confirm_date")
            .order("id")
            .limit(SETTINGS.CONFIRM_PAGE_SIZE)
        )
        if cursor:
            cdate, cid = cursor
            query = query.or_(
                f"confirm_date.gt.{cdate},and(confirm_date.eq.{cdate},id.gt.{cid})"
            )
        return query.execute().data or []

    # ==================== 单笔 ====================

    def _process(self, order: dict, today: date, worker: str, counters: dict) -> str:
        order_id = order.get("id")
        fund_code = order.get("fund_code")

        # 1. 日期与快照守卫（缺失一律转人工，不猜）
        accepted = _as_date(order.get("accepted_date"))
        if accepted is None:
            return self._manual(order_id, worker, "ACCEPTED_DATE_MISSING",
                                "订单缺少受理日 accepted_date，无法确定成交净值日")
        if not order.get("confirm_date"):
            return self._manual(order_id, worker, "CONFIRM_DATE_MISSING",
                                "订单缺少 confirm_date")
        snapshot = order.get("fee_rule_snapshot")
        if not snapshot:
            return self._manual(order_id, worker, "FEE_SNAPSHOT_MISSING",
                                "订单缺少费率快照，不能用当前规则重算")

        # 2. 重试上限与超期（用自然日，确认路径不依赖交易日历）
        try:
            attempts = int(order.get("attempt_count") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= SETTINGS.CONFIRM_MAX_ATTEMPTS:
            return self._manual(order_id, worker, "MAX_ATTEMPTS_EXCEEDED",
                                f"已尝试 {attempts} 次仍未成功")
        age_days = (today - accepted).days
        if age_days > SETTINGS.PENDING_MAX_DAYS:
            return self._manual(order_id, worker, "PENDING_TOO_LONG",
                                f"受理日 {accepted} 距今 {age_days} 天仍未确认")
        if age_days > SETTINGS.NAV_PENDING_ALERT_DAYS:
            logger.warning(
                "[确认] order_id=%s fund=%s accepted_date=%s 已等待 %s 天仍未确认",
                order_id, fund_code, accepted, age_days,
            )

        # 3. 取成交净值日的净值（只读 DB，不触网）
        nav_status, nav = self._nav_for(fund_code, accepted)
        if nav_status == "no_nav":
            return self._manual(order_id, worker, "NO_NAV",
                                f"{fund_code} 在 {accepted} 确实没有净值")
        if nav_status != "ok":
            code = ("NAV_NOT_YET_PUBLISHED" if nav_status == "not_yet_published"
                    else "NAV_FETCH_FAILED")
            logger.info(
                "[确认] 净值不可用，订单保持 pending: order=%s fund=%s date=%s status=%s code=%s",
                order_id, fund_code, accepted, nav_status, code,
            )
            return "skipped_nav"

        if order.get("direction") == "buy":
            return self._confirm_buy(order, worker, accepted, nav)
        return self._confirm_sell(order, worker, today, accepted, nav)

    def _confirm_buy(self, order: dict, worker: str, accepted: date,
                     nav: Decimal) -> str:
        order_id = order.get("id")
        fund_code = order.get("fund_code")
        snapshot = order.get("fee_rule_snapshot")
        try:
            amount = Decimal(str(order.get("amount")))
        except (InvalidOperation, TypeError):
            return self._manual(order_id, worker, "INVALID_AMOUNTS", "订单金额无法解析")

        fee_info = self.fee.calc_purchase_fee(fund_code, float(amount), rule=snapshot)
        if fee_info is None:
            return self._manual(order_id, worker, "FEE_SNAPSHOT_MISSING",
                                "快照里没有可用的申购费率档位")
        fee = Decimal(str(fee_info["fee"]))

        try:
            amounts = calc_buy_amounts(amount, nav, fee)
        except ValueError as exc:
            return self._manual(order_id, worker, "INVALID_AMOUNTS", str(exc))

        payload = self._call_rpc("confirm_buy_order", {
            "p_order_id": order_id,
            "p_worker": worker,
            "p_nav": float(nav),
            "p_fee": float(amounts["fee"]),
            "p_net_amount": float(amounts["net_amount"]),
            "p_quantity": float(amounts["quantity"]),
            "p_residual": float(amounts["residual"]),
        }, order_id, worker)
        return self._log_and_count(order, payload)

    def _confirm_sell(self, order: dict, worker: str, today: date,
                      accepted: date, nav: Decimal) -> str:
        order_id = order.get("id")
        fund_code = order.get("fund_code")
        snapshot = order.get("fee_rule_snapshot")
        try:
            quantity = Decimal(str(order.get("quantity")))
        except (InvalidOperation, TypeError):
            return self._manual(order_id, worker, "INVALID_AMOUNTS", "订单份额无法解析")

        if quantity <= 0:
            return self._manual(order_id, worker, "INVALID_AMOUNTS",
                                f"卖单份额必须为正，实际 {quantity}")

        lots = self._load_lots(order.get("user_id"), fund_code)
        picked, short = select_fifo_lots(lots, quantity, accepted)
        if short > 0:
            return self._manual(order_id, worker, "LOT_INSUFFICIENT",
                                f"可用批次份额不足 {short}，下单时已校验，属数据不一致")

        plan, total_fee = build_sell_plan(
            picked, nav, accepted,
            lambda amount, hold_days: self.fee.calc_redemption_fee(
                fund_code, amount, hold_days, rule=snapshot),
        )
        if total_fee is None:
            return self._manual(order_id, worker, "FEE_SNAPSHOT_MISSING",
                                "快照里没有可用的赎回费率档位")

        payload = self._call_rpc("confirm_sell_order", {
            "p_order_id": order_id,
            "p_worker": worker,
            "p_nav": float(nav),
            "p_plan": plan,
        }, order_id, worker)

        outcome = self._log_and_count(order, payload)
        # 确认晚于到账日：同一轮立即入账（只入一次，RPC 状态 CAS 保证）
        settle_date = _as_date(payload.get("settle_date"))
        if payload.get("result") == "settling" and settle_date and settle_date <= today:
            self._settle_one(order_id, worker, today)
        return outcome

    def _settle_due(self, worker: str, today: date) -> int:
        rows = (
            self.client.table("trade_orders")
            .select("id")
            .eq("status", "settling")
            .lte("settle_date", today.isoformat())
            .order("settle_date")
            .order("id")
            .limit(SETTINGS.CONFIRM_MAX_ORDERS)
            .execute()
        ).data or []

        settled = 0
        for row in rows:
            if self._settle_one(row.get("id"), worker, today):
                settled += 1
        return settled

    def _settle_one(self, order_id: str, worker: str, today: date) -> bool:
        try:
            payload = self._rpc("settle_redeem_order", {
                "p_order_id": order_id,
                "p_worker": worker,
                "p_today": today.isoformat(),
            })
        except Exception as exc:
            if _is_connection_error(exc):
                raise
            logger.error("[确认] 到账失败 order_id=%s: %s", order_id, exc, exc_info=True)
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("result") == "settled":
            logger.info("[确认] 到账完成 order_id=%s net_amount=%s",
                        order_id, payload.get("net_amount"))
            return True
        if payload.get("result") == "manual_review":
            logger.error("[确认] 到账需人工 (result=manual_review) order_id=%s code=%s",
                         order_id, payload.get("code"))
        return False

    # ==================== 工具 ====================

    def _nav_for(self, fund_code: str, nav_date: date) -> tuple[str, Optional[Decimal]]:
        """读指定日净值（单轮内缓存）。返回 (状态, 净值)。"""
        if fund_code == MONEY_FUND_CODE:
            return "ok", Decimal("1.0000")

        key = (fund_code, nav_date)
        cached = self._nav_cache.get(key)
        if cached is not None:
            return cached

        from server.services.fund_nav_service import NavLookupStatus

        lookup = self.nav.get_nav_on(fund_code, nav_date)
        if lookup.status == NavLookupStatus.OK:
            result = ("ok", Decimal(str(lookup.point.unit_nav)))
        elif lookup.status == NavLookupStatus.NO_NAV:
            result = ("no_nav", None)
        else:
            result = (lookup.status.value, None)
        self._nav_cache[key] = result
        return result

    def _load_lots(self, user_id: str, fund_code: str) -> list[dict]:
        return (
            self.client.table("position_lots")
            .select("id, nav_date, available_date, remaining_qty, remaining_cost")
            .eq("user_id", user_id)
            .eq("fund_code", fund_code)
            .order("nav_date")
            .order("created_at")
            .order("id")
            .execute()
        ).data or []

    def _manual(self, order_id: str, worker: str, code: str, message: str) -> str:
        try:
            self._rpc("mark_order_manual_review", {
                "p_order_id": order_id,
                "p_worker": worker,
                "p_code": code,
                "p_message": message[:500],
            })
        except Exception as exc:
            if _is_connection_error(exc):
                raise
            logger.error("[确认] 转人工失败 order_id=%s code=%s: %s",
                         order_id, code, exc, exc_info=True)
            return "retryable"
        logger.error("[确认] 转人工 order_id=%s code=%s message=%s", order_id, code, message)
        return "manual_review"

    def _call_rpc(self, name: str, params: dict,
                  order_id: str, worker: str) -> dict:
        """调用写 RPC，返回统一形状的 dict（异常也映射成 result）。"""
        try:
            payload = self._rpc(name, params)
        except Exception as exc:
            if _is_connection_error(exc):
                raise
            text = str(exc)
            if "duplicate key" in text or "unique constraint" in text:
                # 同一订单重复写业务数据：重试只会永远撞同一约束
                self._manual(order_id, worker, "DUPLICATE_SIDE_EFFECT", text[:200])
                return {"result": "manual_review", "code": "DUPLICATE_SIDE_EFFECT"}
            logger.error("[确认] RPC %s 失败 order_id=%s: %s", name, order_id, exc,
                         exc_info=True)
            return {"result": "retryable", "code": "DB_ERROR"}
        return payload if isinstance(payload, dict) else {"result": "retryable",
                                                          "code": "DB_ERROR"}

    def _log_and_count(self, order: dict, payload: dict) -> str:
        outcome = classify_rpc_result(payload)
        level = logging.INFO
        if outcome in ("rejected", "retryable"):
            level = logging.WARNING
        elif outcome in ("manual_review", "error"):
            level = logging.ERROR
        logger.log(
            level,
            "[确认] order_id=%s user_id=%s fund_code=%s accepted_date=%s "
            "confirm_date=%s result=%s code=%s",
            order.get("id"), order.get("user_id"), order.get("fund_code"),
            order.get("accepted_date"), order.get("confirm_date"),
            payload.get("result"), payload.get("code") or payload.get("status"),
        )
        return outcome

    def _reap_stale(self) -> None:
        reaped = self._rpc("reap_stale_processing", {
            "p_lease_seconds": SETTINGS.CONFIRM_LEASE_SECONDS,
            "p_max_attempts": SETTINGS.CONFIRM_MAX_ATTEMPTS,
        })
        if isinstance(reaped, dict) and (reaped.get("released") or reaped.get("manual")):
            logger.warning("[确认] 回收过期租约: %s", reaped)

    def _finish(self, run_id: str, status: str, counters: dict,
                error: Optional[str]) -> None:
        self._rpc("finish_confirm_run", {
            "p_run_id": run_id,
            "p_status": status,
            "p_counts": counters,
            "p_error": error,
        })

    def _rpc(self, name: str, params: dict):
        return self.client.rpc(name, params).execute().data

    def _result(self, status: str, run_id, counters: dict, today: date,
                trigger: str, message: str, duration_ms: int = 0) -> dict:
        result = {
            "status": status,
            "message": message,
            "run_id": run_id,
            "trigger": trigger,
            "trade_date": today.isoformat(),
            "duration_ms": duration_ms,
        }
        result.update(counters)
        # 旧字段别名：老调度/老接口仍按 processed/skipped 读
        result["processed"] = counters["scanned"]
        result["skipped"] = counters["skipped_nav"] + counters["retryable"]
        return result


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_connection_error(exc: Exception) -> bool:
    """连接/超时类故障：本轮中止，订单不动，下一轮整体重试。"""
    if type(exc).__name__ in _CONNECTION_ERROR_TYPES:
        return True
    text = str(exc).lower()
    return any(k in text for k in ("connection", "timed out", "timeout",
                                   "server disconnected"))
