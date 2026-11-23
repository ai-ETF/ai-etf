"""
场外基金白名单同步 —— 手动触发入口（运维用）

用法:
    cd /root/ai-etf && .venv/bin/python -m server.scripts.sync_fund_catalog [选项]

    --limit N       只处理前 N 只基金（试跑，如 --limit 5）
    --codes A,B     只处理指定基金代码（逗号分隔）
    --interval S    逐只抓取间隔秒数，默认 0.3（沿用同步模块常量）
    --dry-run       抓取并组装，但不写库

退出码:
    0  成功（无失败行）
    1  有失败行或运行异常
    2  已有同步在跑（未取到 sync_lock）

为什么需要这个脚本:
    白名单同步原本只有进程内 APScheduler 的定时入口（每天 02:17），运维无法立刻触发；
    而生产环境变量由 server/app.py 的 load_dotenv 注入（systemd 未配置 EnvironmentFiles），
    裸跑一次性命令会因缺 SUPABASE_URL 直接失败 —— 本脚本自己加载 .env 解决。
    与定时任务共用 sync_lock，两轮同步不会同时写同一批 fund_code。

全量约 2286 只、耗时 20-30 分钟，建议后台跑:
    setsid nohup .venv/bin/python -m server.scripts.sync_fund_catalog \\
        > /tmp/fund_sync_$(date +%m%d_%H%M).log 2>&1 < /dev/null &
"""
import argparse
import logging
import os
import sys

# 环境变量必须在导入 server.* 之前加载（与 server/app.py 相同的口径）
from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(dotenv_path=os.path.join(_PROJECT_ROOT, ".env"))

from server.services.fund_catalog_sync import (  # noqa: E402  (须在 load_dotenv 之后)
    DEFAULT_REQUEST_INTERVAL,
    FundCatalogSync,
    SyncLockBusy,
    sync_lock,
)

logger = logging.getLogger("fund_catalog_sync_cli")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="手动触发场外基金白名单同步")
    parser.add_argument("--limit", type=int, default=None,
                        help="只处理前 N 只基金（试跑用）")
    parser.add_argument("--codes", type=str, default=None,
                        help="只处理指定基金代码，逗号分隔，如 --codes 110020,000071")
    parser.add_argument("--interval", type=float, default=DEFAULT_REQUEST_INTERVAL,
                        help=f"逐只抓取间隔秒数，默认 {DEFAULT_REQUEST_INTERVAL}")
    parser.add_argument("--dry-run", action="store_true",
                        help="抓取并组装但不写库")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    codes = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None

    try:
        with sync_lock():
            stats = FundCatalogSync().run(
                codes=codes,
                limit=args.limit,
                interval=args.interval,
                dry_run=args.dry_run,
            )
    except SyncLockBusy as e:
        logger.error(f"中止：{e}")
        return 2

    print(f"[统计] {stats}")
    if stats["failed"]:
        logger.warning(f"本轮有 {stats['failed']} 只写入失败，详见上方日志（不影响其余基金）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
