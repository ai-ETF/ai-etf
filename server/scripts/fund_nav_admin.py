"""
场外基金净值运维入口（手动触发）

用法:
    cd /root/ai-etf && .venv/bin/python -m server.scripts.fund_nav_admin <子命令> [参数]

    status                          查看覆盖率、净值行数、最近失败
    update [--codes A,B]            刷新最新净值（默认全白名单）
    history CODE [CODE ...]         补齐历史净值（幂等，已 ready 直接跳过）
    repair CODE DATE                补某只基金某一天的缺口（先近端再全量）
    meta CODE [CODE ...]            查看基金主数据（经理/公司/QDII 等）
    warm [--pause S]                持仓基金历史预热（逐只限速）

退出码:
    0  成功
    1  有失败（detail 见输出，部分失败也算 1）
    2  已有净值更新在跑（未取到 flock 锁）

为什么需要这个脚本:
    净值的写入入口是调度器（`spot_cache_scheduler`），出问题时运维需要立刻手动补一轮；
    与定时任务共用 `/tmp/fund_nav_update.lock`，不会并发写同一批基金。
    生产环境变量由 `server/app.py` 的 load_dotenv 注入，裸跑一次性命令会因缺
    SUPABASE_URL 直接失败 —— 本脚本自己先加载 .env 再 import server.*。
"""
import argparse
import dataclasses
import json
import logging
import os
import sys

# 环境变量必须在导入 server.* 之前加载（与 server/app.py 相同的口径）
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

from server.services.fund_meta_service import FundMetaService  # noqa: E402
from server.services.fund_nav_sync_service import (  # noqa: E402
    FundNavSyncService,
    NavLockBusy,
)

logger = logging.getLogger("fund_nav_admin")


def _codes(value):
    return [c.strip() for c in value.split(",") if c.strip()] if value else None


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="场外基金净值运维入口")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看净值覆盖率与最近失败")

    p_update = sub.add_parser("update", help="刷新最新净值")
    p_update.add_argument("--codes", type=str, default=None,
                          help="只更新指定代码，逗号分隔；默认全白名单")

    p_history = sub.add_parser("history", help="补齐历史净值")
    p_history.add_argument("codes", nargs="+", help="基金代码，空格分隔")

    p_repair = sub.add_parser("repair", help="补某只基金某一天的缺口")
    p_repair.add_argument("code", help="基金代码")
    p_repair.add_argument("date", help="净值日期 YYYY-MM-DD")

    p_meta = sub.add_parser("meta", help="查看基金主数据")
    p_meta.add_argument("codes", nargs="+", help="基金代码，空格分隔")

    p_warm = sub.add_parser("warm", help="持仓基金历史预热")
    p_warm.add_argument("--pause", type=float, default=0.5,
                        help="逐只间隔秒数，默认 0.5")
    return parser.parse_args(argv)


def _cmd_status(sync: FundNavSyncService) -> int:
    print(json.dumps(sync.describe(), ensure_ascii=False, indent=2, default=str))
    return 0


def _cmd_update(sync: FundNavSyncService, codes) -> int:
    try:
        result = sync.update_batch(codes=codes)
    except NavLockBusy as exc:
        logger.error(f"中止：{exc}")
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, default=str))
    return 1 if result.failed else 0


def _cmd_history(sync: FundNavSyncService, codes) -> int:
    failed = 0
    for code in codes:
        result = sync.ensure_history(code)
        print(json.dumps({
            "fund_code": result.fund_code,
            "status": result.status,
            "inserted": result.inserted,
            "revised": result.revised,
            "start_date": result.start_date,
            "error": result.error,
            "elapsed_ms": result.elapsed_ms,
        }, ensure_ascii=False, default=str))
        if not result.ok:
            failed += 1
    return 1 if failed else 0


def _cmd_repair(sync: FundNavSyncService, code: str, raw_date: str) -> int:
    from datetime import date

    try:
        on_date = date.fromisoformat(raw_date)
    except ValueError:
        logger.error(f"日期格式非法（需 YYYY-MM-DD）: {raw_date!r}")
        return 1

    lookup = sync.repair(code, on_date)
    print(json.dumps({
        "fund_code": code,
        "nav_date": on_date.isoformat(),
        "status": lookup.status.value,
        "reason": lookup.reason,
        "unit_nav": str(lookup.point.unit_nav) if lookup.point else None,
    }, ensure_ascii=False))
    # NOT_YET_PUBLISHED / NO_NAV 也是「明确答案」，不算失败；只有补数失败返回 1
    return 0 if lookup.status.value in ("ok", "not_yet_published", "no_nav") else 1


def _cmd_meta(codes) -> int:
    metas = FundMetaService().get_batch(codes)
    missing = [c for c in codes if c not in metas]
    for code in codes:
        meta = metas.get(code)
        print(json.dumps(
            dataclasses.asdict(meta) if meta else {"fund_code": code, "missing": True},
            ensure_ascii=False,
            default=str,
        ))
    return 1 if missing else 0


def _cmd_warm(sync: FundNavSyncService, pause: float) -> int:
    results = sync.warm_positions(pause=pause)
    for result in results:
        print(json.dumps({
            "fund_code": result.fund_code,
            "status": result.status,
            "inserted": result.inserted,
            "error": result.error,
        }, ensure_ascii=False))
    return 1 if any(not r.ok for r in results) else 0


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    sync = FundNavSyncService()

    if args.command == "status":
        return _cmd_status(sync)
    if args.command == "update":
        return _cmd_update(sync, _codes(args.codes))
    if args.command == "history":
        return _cmd_history(sync, args.codes)
    if args.command == "repair":
        return _cmd_repair(sync, args.code, args.date)
    if args.command == "meta":
        return _cmd_meta(args.codes)
    if args.command == "warm":
        return _cmd_warm(sync, args.pause)
    return 1  # argparse 已保证不可达


if __name__ == "__main__":
    sys.exit(main())
