"""订单运维入口（对账 / 卡单 / 人工重排 / 拒单）。

用法::

    poetry run python -m server.scripts.order_ops reconcile
    poetry run python -m server.scripts.order_ops list-manual [--limit 50]
    poetry run python -m server.scripts.order_ops list-stuck [--limit 50]
    poetry run python -m server.scripts.order_ops requeue <order_id> --reason "已补净值" [--yes]
    poetry run python -m server.scripts.order_ops reject <order_id> --code NO_NAV --message "停牌退市" [--yes]

设计来源：《订单确认-执行机制》§3.11（人工出口）、§3.14.3（对账脚本）。

退出码：0 = 正常；1 = 对账有差异或操作被拒绝；2 = 参数/环境错误。

写操作（`requeue` / `reject`）默认要求交互确认，`--yes` 跳过；两者的实际写库与
幂等校验都在 RPC 里（`requeue_manual_review_order` / `reject_trade_order`），
脚本只负责选单、展示与调用，不自己拼业务写操作。
"""
import argparse
import json
import logging
import os
import socket
import sys
from datetime import timedelta

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

from server.config.settings import SETTINGS  # noqa: E402
from server.services.trading_calendar import beijing_now  # noqa: E402
from server.storage.supabase_client import get_supabase  # noqa: E402

logger = logging.getLogger("order_ops")

ORDER_FIELDS = ("id,user_id,fund_code,fund_name,direction,status,amount,quantity,"
                "accepted_date,confirm_date,settle_date,attempt_count,"
                "last_error_code,last_error_message,updated_at")


def _admin_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:order_ops"


def _client():
    client = get_supabase()
    if client is None:
        raise RuntimeError("Supabase 客户端不可用（检查 SUPABASE_URL / SERVICE_ROLE_KEY）")
    return client


# ==================== 只读命令 ====================


def cmd_reconcile(client) -> int:
    """跑 §9.3 十条不变量；有差异返回 1（供 cron/人工判断）。"""
    result = client.rpc("reconcile_orders", {}).execute().data or {}
    checks = result.get("checks") or []
    failing = [c for c in checks if int(c.get("count") or 0) > 0]

    print(json.dumps({
        "checked_at": result.get("checked_at"),
        "failed_checks": result.get("failed_checks"),
        "rows_total": result.get("rows_total"),
        "failing": [{"name": c["name"], "count": c["count"],
                     "truncated": c.get("truncated"), "rows": c.get("rows")}
                    for c in failing],
    }, ensure_ascii=False, indent=2, default=str))

    if failing:
        logger.error("[对账] 发现 %s 项差异、%s 行",
                     result.get("failed_checks"), result.get("rows_total"))
        return 1
    logger.info("[对账] 全部 %s 项检查通过", len(checks))
    return 0


def cmd_list_manual(client, limit: int) -> int:
    rows = (client.table("trade_orders").select(ORDER_FIELDS)
            .eq("status", "manual_review").order("updated_at").limit(limit)
            .execute()).data or []
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_list_stuck(client, limit: int) -> int:
    """三类卡单：待确认超期、确认中租约过期、卖出到账日已过仍未入账。"""
    now = beijing_now()
    nav_threshold = (now.date() - timedelta(days=SETTINGS.NAV_PENDING_ALERT_DAYS)).isoformat()
    lease_threshold = (now - timedelta(seconds=SETTINGS.CONFIRM_LEASE_SECONDS)).isoformat()

    pending = (client.table("trade_orders").select(ORDER_FIELDS)
               .eq("status", "pending").lt("accepted_date", nav_threshold)
               .order("accepted_date").limit(limit).execute()).data or []
    processing = (client.table("trade_orders").select(ORDER_FIELDS)
                  .eq("status", "processing").lt("processing_at", lease_threshold)
                  .order("processing_at").limit(limit).execute()).data or []
    settling = (client.table("trade_orders").select(ORDER_FIELDS)
                .eq("status", "settling").lt("settle_date", now.date().isoformat())
                .order("settle_date").limit(limit).execute()).data or []

    print(json.dumps({
        "as_of": now.isoformat(),
        "thresholds": {
            "pending_accepted_before": nav_threshold,
            "processing_lease_before": lease_threshold,
            "settling_settle_before": now.date().isoformat(),
        },
        "pending_overdue": pending,
        "processing_stale": processing,
        "settling_overdue": settling,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


# ==================== 写命令 ====================


def _load_order(client, order_id: str):
    rows = (client.table("trade_orders").select(ORDER_FIELDS)
            .eq("id", order_id).limit(1).execute()).data or []
    if not rows:
        logger.error("订单不存在: %s", order_id)
        return None
    return rows[0]


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:  # 非交互环境没给 --yes：按拒绝处理，不静默执行
        logger.error("非交互环境，写操作需要 --yes 确认")
        return False


def cmd_requeue(client, order_id: str, reason: str, assume_yes: bool) -> int:
    order = _load_order(client, order_id)
    if order is None:
        return 1
    print(json.dumps(order, ensure_ascii=False, indent=2, default=str))
    if order["status"] != "manual_review":
        logger.error("只有 manual_review 可以重排，当前状态 %s", order["status"])
        return 1
    if not _confirm(f"确认把订单 {order_id} 重排回 pending？", assume_yes):
        logger.info("已取消")
        return 1

    result = client.rpc("requeue_manual_review_order", {
        "p_order_id": order_id, "p_admin": _admin_id(), "p_reason": reason,
    }).execute().data
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if isinstance(result, dict) and result.get("result") == "requeued" else 1


def cmd_reject(client, order_id: str, code: str, message: str, assume_yes: bool) -> int:
    order = _load_order(client, order_id)
    if order is None:
        return 1
    print(json.dumps(order, ensure_ascii=False, indent=2, default=str))
    if not _confirm(f"确认拒单 {order_id}（{code}）？买入会退回冻结资金", assume_yes):
        logger.info("已取消")
        return 1

    result = client.rpc("reject_trade_order", {
        "p_order_id": order_id, "p_worker": _admin_id(),
        "p_code": code, "p_message": message,
    }).execute().data
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if isinstance(result, dict) and result.get("result") == "rejected" else 1


# ==================== 入口 ====================


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="订单运维入口")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("reconcile", help="跑对账不变量（有差异退出码 1）")

    p_manual = sub.add_parser("list-manual", help="列 manual_review 订单")
    p_manual.add_argument("--limit", type=int, default=50)

    p_stuck = sub.add_parser("list-stuck", help="列卡单（待确认超期/租约过期/到账超期）")
    p_stuck.add_argument("--limit", type=int, default=50)

    p_requeue = sub.add_parser("requeue", help="把 manual_review 订单重排回 pending")
    p_requeue.add_argument("order_id")
    p_requeue.add_argument("--reason", required=True)
    p_requeue.add_argument("--yes", action="store_true")

    p_reject = sub.add_parser("reject", help="拒单（买入退款、卖出撤销）")
    p_reject.add_argument("order_id")
    p_reject.add_argument("--code", required=True)
    p_reject.add_argument("--message", default="")
    p_reject.add_argument("--yes", action="store_true")

    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        client = _client()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2

    if args.command == "reconcile":
        return cmd_reconcile(client)
    if args.command == "list-manual":
        return cmd_list_manual(client, args.limit)
    if args.command == "list-stuck":
        return cmd_list_stuck(client, args.limit)
    if args.command == "requeue":
        return cmd_requeue(client, args.order_id, args.reason, args.yes)
    if args.command == "reject":
        return cmd_reject(client, args.order_id, args.code, args.message, args.yes)
    return 2  # argparse 已保证不可达


if __name__ == "__main__":
    sys.exit(main())
