"""
ETF 预约订单调度器

在交易时段（9:30-11:30、13:00-15:00）定时检查并执行所有 status='reserved' 的预约单。
复用 spot_cache_scheduler.py 的 APScheduler 模式。
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _is_etf_trading_time() -> bool:
    """判断当前是否为 ETF 交易时段"""
    from server.services.trading_calendar import is_etf_trading_time
    from server.services.portfolio_service import _beijing_now
    return is_etf_trading_time(_beijing_now())


def _execute_reserved_orders():
    """执行所有待执行的预约单"""
    if not _is_etf_trading_time():
        return

    from server.services.portfolio_service import PortfolioService
    svc = PortfolioService()
    result = svc.execute_reservations()

    if result["executed"] > 0 or result["failed"] > 0:
        logger.info(
            f"预约执行完成: 成功 {result['executed']} 笔, 失败 {result['failed']} 笔"
        )


def start_scheduler() -> AsyncIOScheduler:
    """启动预约执行调度器"""
    global _scheduler

    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        _execute_reserved_orders,
        trigger=IntervalTrigger(seconds=60),
        id="execute_reserved_orders",
        name="执行ETF预约订单（交易时段每60秒检查）",
        replace_existing=True,
    )
    logger.info("ETF预约订单调度器已注册（每60秒检查一次）")

    _scheduler.start()
    return _scheduler


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("ETF预约订单调度器已停止")
        _scheduler = None
