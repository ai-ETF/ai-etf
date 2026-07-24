"""
行情缓存定时刷新调度器

独立管理全量ETF行情的定时拉取，与 API 接口逻辑解耦。
API 请求只读缓存，不会触发全量拉取。
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _is_trading_time() -> bool:
    """判断当前是否为A股交易时段（9:30-15:00，工作日）"""
    import datetime
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return False
    if now.hour >= 15:
        return False
    return True


async def _warmup_cache():
    """启动时异步预热行情缓存"""
    from server.services.finance_api_service import FinanceApiService
    logger.info("[预热] 开始首次全量行情加载...")
    success = FinanceApiService.refresh_spot_cache()
    if success:
        logger.info("[预热] 全量行情加载完成")
    else:
        logger.warning("[预热] 全量行情加载失败，将等待定时任务重试")


def start_scheduler() -> AsyncIOScheduler:
    """启动定时刷新调度器，返回 scheduler 实例"""
    global _scheduler
    from server.services.finance_api_service import FinanceApiService

    _scheduler = AsyncIOScheduler()

    _scheduler.add_job(
        FinanceApiService.refresh_spot_cache,
        trigger=IntervalTrigger(seconds=30),
        id="refresh_etf_spot",
        name="刷新ETF全量行情缓存（交易时段30s/非交易时段跳过）",
        replace_existing=True,
    )
    logger.info("ETF行情定时刷新任务已注册（每30秒检测一次）")

    _scheduler.start()

    # 不阻塞启动，异步执行首次预热
    asyncio.ensure_future(_warmup_cache())

    return _scheduler


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("ETF行情定时刷新任务已停止")
        _scheduler = None