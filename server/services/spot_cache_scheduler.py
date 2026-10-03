"""
行情缓存定时刷新调度器 + Pending 订单确认

独立管理：
1. 全量 ETF 行情的定时拉取（交易时段 30s；交易时段判定见 trading_calendar）
2. Pending 订单确认（每个交易日 15:37）
3. 货基万份收益入账（每天 00:05）
4. 场外基金白名单同步（每天 02:17）
5. 启动时补偿：检查遗漏的 pending 订单并立即确认
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _warmup_cache():
    """启动时异步预热行情缓存"""
    from server.services.finance_api_service import FinanceApiService
    logger.info("[预热] 开始首次全量行情加载...")
    success = FinanceApiService.refresh_spot_cache()
    if success:
        logger.info("[预热] 全量行情加载完成")
    else:
        logger.warning("[预热] 全量行情加载失败，将等待定时任务重试")


async def _confirm_pending_orders_job():
    """Pending 订单确认任务（每个交易日 15:37 执行）"""
    from server.services.portfolio_service import PortfolioService
    logger.info("[确认] 开始检查 pending 订单...")
    svc = PortfolioService()
    result = svc.confirm_pending_orders(skip_trading_day_check=False)
    logger.info(f"[确认] Pending 订单确认完成: {result}")


async def _credit_money_fund_income_job():
    """货基每日收益入账任务（每天 00:05 执行）。

    把「昨日」公布的万份收益折算成份额，加到所有货基持仓的 quantity
    （份额逐日增长，即复投；本金 principal 不变）。
    数据源失败时 credit_money_fund_income 会抛异常（不兜底），
    此处捕获后记录错误并重新抛出，让调度器将其标记为失败任务，
    避免当天用虚假数字入账。
    """
    from server.services.portfolio_service import PortfolioService
    logger.info("[货基收益] 开始每日收益入账...")
    svc = PortfolioService()
    try:
        result = svc.credit_money_fund_income()
        logger.info(f"[货基收益] 每日收益入账完成: {result}")
    except Exception as e:
        # 无兜底：明确失败并上抛，不静默跳过（宁可当天不入账）
        logger.error(f"[货基收益] 每日收益入账失败（未入账）: {e}", exc_info=True)
        raise


async def _fund_catalog_sync_job():
    """场外基金白名单同步任务（每天 02:17 执行）。

    全量抓取场外 ETF 联接基金的费率与风险画像，幂等 upsert 进
    fund_fee_rules + fund_risk_profiles。数千只基金逐只抓取耗时约 20-30 分钟，
    必须放到线程中执行 —— 直接在事件循环里跑 requests + sleep 会阻塞整个服务。
    单只基金失败不影响其余基金（run 内部逐只捕获异常）。
    """
    from server.services.fund_catalog_sync import FundCatalogSync

    logger.info("[基金同步] 开始同步场外 ETF 联接基金白名单...")
    svc = FundCatalogSync()
    result = await asyncio.to_thread(svc.run)
    logger.info(f"[基金同步] 完成: {result}")


async def _startup_pending_compensation():
    """启动补偿：确认所有遗漏的 pending 订单（不检查交易日）"""
    from server.services.portfolio_service import PortfolioService
    logger.info("[启动补偿] 检查遗漏的 pending 订单...")
    svc = PortfolioService()
    result = svc.confirm_pending_orders(skip_trading_day_check=True)
    logger.info(f"[启动补偿] 遗漏订单确认完成: {result}")


def start_scheduler() -> AsyncIOScheduler:
    """启动定时刷新调度器 + Pending 确认调度器，返回 scheduler 实例"""
    global _scheduler
    from server.services.finance_api_service import FinanceApiService

    _scheduler = AsyncIOScheduler()

    # 任务1：ETF 行情缓存刷新（交易时段每30秒）
    _scheduler.add_job(
        FinanceApiService.refresh_spot_cache,
        trigger=IntervalTrigger(seconds=30),
        id="refresh_etf_spot",
        name="刷新ETF全量行情缓存（交易时段30s/非交易时段跳过）",
        replace_existing=True,
    )
    logger.info("ETF行情定时刷新任务已注册（每30秒检测一次）")

    # 任务2：Pending 订单确认（每个交易日 15:37）
    _scheduler.add_job(
        _confirm_pending_orders_job,
        trigger=CronTrigger(hour=15, minute=37, day_of_week="mon-fri"),
        id="confirm_pending_orders",
        name="确认pending订单（每个交易日15:37）",
        replace_existing=True,
        misfire_grace_time=3600,  # 错过1小时内仍可补执行
    )
    logger.info("Pending订单确认任务已注册（每个交易日15:37，1小时容错）")

    # 任务3：货基每日收益入账（每天 00:05）
    # 货基当日万份收益通常在晚间披露，00:05 运行时拿到的即昨日完整收益。
    # 数据源失败时任务内会抛错，由调度器记录，不会用兜底数字入账。
    _scheduler.add_job(
        _credit_money_fund_income_job,
        trigger=CronTrigger(hour=0, minute=5),
        id="credit_money_fund_income",
        name="货基万份收益每日入账（每天00:05）",
        replace_existing=True,
        misfire_grace_time=3600,  # 错过1小时内仍可补执行
    )
    logger.info("货基收益入账任务已注册（每天00:05，1小时容错）")

    # 任务4：场外基金白名单同步（每天 02:17）
    # 选在凌晨非交易时段：不影响下单，也避开 00:05 的货基收益入账。
    # 全量抓取耗时较长（数千只基金逐只抓页面），容错窗口给到 2 小时。
    _scheduler.add_job(
        _fund_catalog_sync_job,
        trigger=CronTrigger(hour=2, minute=17),
        id="fund_catalog_sync",
        name="场外基金白名单同步（每天02:17）",
        replace_existing=True,
        misfire_grace_time=7200,
    )
    logger.info("场外基金白名单同步任务已注册（每天02:17，2小时容错）")

    _scheduler.start()

    # 不阻塞启动，异步执行首次预热
    asyncio.ensure_future(_warmup_cache())
    # 启动补偿：检查遗漏的 pending 订单
    asyncio.ensure_future(_startup_pending_compensation())

    return _scheduler


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")
        _scheduler = None
