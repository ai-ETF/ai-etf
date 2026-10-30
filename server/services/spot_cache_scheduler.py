"""
定时任务调度器（Pending 订单确认 / 净值 / 白名单同步 / 货基收益）

独立管理：
1. Pending 订单确认（每个交易日 15:37，只补历史遗漏）
2. 货基万份收益入账（每天 00:05）
3. 场外基金白名单同步（每天 02:17）
4. 场外基金最新净值更新 + 确认（交易日 18:00 起多轮，见 `_fund_nav_update_job`）
5. 启动时补偿：净值补跑 + 检查遗漏的 pending 订单

2026-10-26：场内 ETF 的 30 秒行情轮询（`refresh_etf_spot`）与启动预热
（`_warmup_cache`）已删除——产品只做场外基金，净值每日公布一次，不需要实时行情。
文件名沿用 `spot_cache_scheduler`（改名会牵动全部 import，留作已知残留）。
"""
import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _confirm_pending_orders_job(before_today: bool = False):
    """Pending 订单确认任务。

    参数:
        before_today: True 只确认 `confirm_date < today`（15:37 的历史遗漏任务）；
                      False 确认到今天（净值公布后的晚间任务、08:05、启动补偿）。

    取不到确认日净值的订单保持 pending 并计入 skipped，不拒单、不退款。
    """
    from server.services.portfolio_service import PortfolioService
    logger.info("[确认] 开始检查 pending 订单...")
    svc = PortfolioService()
    result = svc.confirm_pending_orders(before_today=before_today)
    logger.info(f"[确认] Pending 订单确认完成: {result}")
    return result


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

    全量抓取场外 ETF 联接基金的元数据、费率与风险画像，经 RPC `upsert_fund_catalog`
    一次事务写入 `fund` + `fund_trade_rule` + `fund_risk_profiles`
    （旧表 `fund_fee_rules` 已由 `fund_catalog` 视图兼容）。数千只基金逐只抓取
    耗时约 20-30 分钟，必须放到线程中执行 —— 直接在事件循环里跑 requests + sleep 会阻塞整个服务。
    单只基金失败不影响其余基金（run 内部逐只捕获异常）。

    与手动入口（server/scripts/sync_fund_catalog.py）共用 sync_lock：拿不到锁说明
    已有同步在跑（多半是运维手工触发），本轮跳过即可，不视为失败。
    """
    from server.services.fund_catalog_sync import FundCatalogSync, SyncLockBusy, sync_lock

    logger.info("[基金同步] 开始同步场外 ETF 联接基金白名单...")
    try:
        with sync_lock():
            svc = FundCatalogSync()
            result = await asyncio.to_thread(svc.run)
    except SyncLockBusy as e:
        logger.warning(f"[基金同步] 跳过本轮：{e}")
        return
    logger.info(f"[基金同步] 完成: {result}")


async def _startup_pending_compensation():
    """启动补偿：确认所有到期未确认的 pending 订单（含今天）。"""
    logger.info("[启动补偿] 检查遗漏的 pending 订单...")
    await _confirm_pending_orders_job(before_today=False)


def _is_trading_day_or_none(d) -> bool | None:
    """交易日判定；日历不可用/越界返回 None（调用方自行决定是否放行）。

    净值更新是幂等且只读上游的轻量操作，日历故障时**宁可多跑一轮**，
    也不能因为日历没刷新就让全站净值停更 —— 但必须留下 WARNING。
    """
    from server.services.trading_calendar import (
        CalendarOutOfCoverage,
        CalendarUnavailable,
        is_trading_day,
    )

    try:
        return is_trading_day(d)
    except (CalendarUnavailable, CalendarOutOfCoverage) as exc:
        logger.warning("[净值] 交易日历不可用，按交易日处理: %s", exc)
        return None


async def _warm_positions_job():
    """持仓历史预热：`quantity > 0` 且历史未补齐的基金逐只补齐。

    串行限速放在同步服务内（`pause`），这里整体丢到线程里，避免阻塞事件循环。
    """
    from server.services.fund_nav_sync_service import FundNavSyncService
    try:
        results = await asyncio.to_thread(FundNavSyncService().warm_positions)
    except Exception as exc:  # 预热失败不影响净值更新本身
        logger.error("[净值] 持仓历史预热失败: %s", exc, exc_info=True)
        return
    logger.info("[净值] 持仓历史预热完成: 补齐 %s 只", len(results))


async def _fund_nav_update_job(with_confirm: bool = True, prev_day: bool = False):
    """场外基金最新净值更新（可选随后确认订单）。

    参数:
        with_confirm: 更新后是否立刻跑一次订单确认
        prev_day: True 用「昨天」判断是否交易日（凌晨 00:30/01:30 的收尾轮）

    流程：`update_batch`（写最新一两个点）→ 持仓预热 → 订单确认。
    拿不到单飞锁（已有更新在跑）视为本轮跳过，**不算失败**。
    """
    from server.services.fund_nav_sync_service import FundNavSyncService, NavLockBusy
    from server.services.trading_calendar import beijing_now

    today = beijing_now().date()
    check_date = today - timedelta(days=1) if prev_day else today
    if _is_trading_day_or_none(check_date) is False:
        logger.info("[净值] %s 非交易日，跳过净值更新", check_date)
        return

    try:
        result = await asyncio.to_thread(FundNavSyncService().update_batch)
    except NavLockBusy as exc:
        logger.warning("[净值] 跳过本轮更新：%s", exc)
        return
    except Exception as exc:
        # 更新失败不阻断确认：确认只读 DB，已入库的净值仍可确认
        logger.error("[净值] 最新净值更新失败: %s", exc, exc_info=True)
    else:
        logger.info("[净值] 最新净值更新完成: %s", result.as_dict())
        await _warm_positions_job()

    if with_confirm:
        await _confirm_pending_orders_job(before_today=False)


async def _startup_nav_update():
    """启动补偿：今天还没跑过净值更新就补跑一轮（不载入任何内存缓存）。"""
    from server.services.fund_nav_sync_service import FundNavSyncService

    try:
        result = await asyncio.to_thread(FundNavSyncService().startup_update_if_stale)
    except Exception as exc:
        logger.error("[净值] 启动补偿失败: %s", exc, exc_info=True)
        return
    if result is None:
        logger.info("[净值] 今天已更新过，跳过启动补跑")
        return
    logger.info("[净值] 启动补跑完成: %s", result.as_dict())
    await _warm_positions_job()


async def _startup_nav_and_confirm():
    """启动补偿（串行）：先补净值，再确认遗漏订单。

    两步必须串行：并发跑的话确认会先扫一遍「净值还没入库」的订单，
    全部 skipped，白做一轮。
    """
    await _startup_nav_update()
    await _startup_pending_compensation()



def start_scheduler() -> AsyncIOScheduler:
    """启动定时刷新调度器 + Pending 确认调度器，返回 scheduler 实例"""
    global _scheduler
    from functools import partial

    _scheduler = AsyncIOScheduler()

    # 任务1：Pending 订单确认（每个交易日 15:37）
    # 只补「今天之前」的遗漏：当日净值要到晚间才公布，15:37 确认只会全部跳过，
    # 且会把当日订单的状态搅乱 —— 当日订单一律等任务5的晚间窗口。
    _scheduler.add_job(
        partial(_confirm_pending_orders_job, before_today=True),
        trigger=CronTrigger(hour=15, minute=37, day_of_week="mon-fri"),
        id="confirm_pending_orders",
        name="确认pending订单（每个交易日15:37，只补历史遗漏）",
        replace_existing=True,
        misfire_grace_time=3600,  # 错过1小时内仍可补执行
    )
    logger.info("Pending订单确认任务已注册（每个交易日15:37）")

    # 任务5：场外基金净值更新 + 确认（净值通常在交易日 18:00 后才公布）
    # 多轮重试覆盖「公布晚 / QDII 更晚」的情况；每轮先更新再确认，
    # 确认只读 DB，取不到就保持 pending，等下一轮。
    _scheduler.add_job(
        partial(_fund_nav_update_job, with_confirm=True),
        trigger=CronTrigger(hour="18,19", minute=0),
        id="fund_nav_update_early",
        name="场外净值更新+确认（交易日18:00/19:00）",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    _scheduler.add_job(
        partial(_fund_nav_update_job, with_confirm=True),
        trigger=CronTrigger(hour="20,21,22,23", minute=5),
        id="fund_nav_update_late",
        name="场外净值更新+确认（交易日20:05/21:05/22:05/23:05）",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    # 凌晨收尾轮：按「昨天是否交易日」判断，收晚公布的 QDII / 海外基金；
    # 只更新不确认（确认放到 08:05 那次，避免同一批订单在凌晨被反复扫）
    _scheduler.add_job(
        partial(_fund_nav_update_job, with_confirm=False, prev_day=True),
        trigger=CronTrigger(hour="0,1", minute=30),
        id="fund_nav_update_overnight",
        name="场外净值更新（次日00:30/01:30）",
        replace_existing=True,
        misfire_grace_time=1800,
    )
    # 每天 08:05 补漏：不按交易日判断，覆盖前一夜失败与停机
    _scheduler.add_job(
        partial(_fund_nav_update_job, with_confirm=True, prev_day=False),
        trigger=CronTrigger(hour=8, minute=5),
        id="fund_nav_update_morning",
        name="场外净值更新+确认（每天08:05补漏）",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("场外净值更新任务已注册（18:00/19:00/20:05~23:05/00:30/01:30/08:05）")

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

    # 启动补偿：净值补跑 → 遗漏订单确认（串行）
    asyncio.ensure_future(_startup_nav_and_confirm())

    return _scheduler


def shutdown_scheduler():
    """关闭调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("定时任务已停止")
        _scheduler = None
