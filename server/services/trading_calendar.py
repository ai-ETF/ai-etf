"""A 股交易日历（全项目唯一入口）。

设计依据：`docs/20-设计/基金与交易/交易日历缓存.md`。

契约（对外签名不变）：

- `is_trading_day(d) -> bool`：只在「快照已就绪且日期在覆盖区间内」时返回；
- `is_trading_time(dt) -> bool`：交易日 9:30–15:00，含 9:30、不含 15:00；
- `calendar_status(d)`：把「不知道」与「非交易日」分开；
- `load_calendar_cache()`：进程启动时从 DB 载入快照（不触网）；
- `reset_cache()` / `install_snapshot()`：测试专用。

**无兜底**：快照未载入抛 `CalendarUnavailable`，日期越界抛
`CalendarOutOfCoverage`。不按星期几猜测，也不把「取不到」当成「全年休市」。

历史说明：本模块原先直接调 akshare，并带有「从未取到日历就按工作日判断」的
兜底；2026-10-21 起改为 DB 快照 + 人工刷新，兜底已删除。
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from server.services.trading_calendar_cache import (
    BEIJING_TZ,
    CalendarDataInvalid,
    CalendarOutOfCoverage,
    CalendarRefreshTimeout,
    CalendarSnapshot,
    CalendarStatus,
    CalendarUnavailable,
    RefreshInProgress,
    RefreshResult,
    TradingCalendarCache,
    get_calendar_cache,
)

logger = logging.getLogger(__name__)


def beijing_now() -> datetime:
    """当前北京时间（带时区）"""
    return datetime.now(BEIJING_TZ)


def load_calendar_cache() -> bool:
    """进程启动时从 DB 载入快照；DB 为空/读取失败返回 False（进程继续启动）。"""
    return get_calendar_cache().load_from_db()


def reset_cache() -> None:
    """清空内存快照（测试专用）。

    日历是模块级快照，不清空会让用例之间互相污染；本函数不影响 DB。
    """
    get_calendar_cache().reset()


def install_snapshot(
    trading_days,
    coverage_start: Optional[date] = None,
    coverage_end: Optional[date] = None,
    source: str = "test",
) -> None:
    """测试专用：注入假快照，绕开 DB 与网络。"""
    get_calendar_cache().install_snapshot(
        trading_days,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        source=source,
    )


def calendar_status(d: date) -> CalendarStatus:
    """只读状态：TRADING / NON_TRADING / UNAVAILABLE / OUT_OF_COVERAGE。"""
    return get_calendar_cache().status(d)


def is_trading_day(d: date) -> bool:
    """是否为 A 股交易日。

    快照未就绪 → `CalendarUnavailable`；日期超出覆盖区间 →
    `CalendarOutOfCoverage`；覆盖区间内的周末/节假日返回 `False`。
    """
    return get_calendar_cache().is_trading_day(d)


def next_trading_day(d: date) -> date:
    """`d` 之后的第一个交易日（严格大于 `d`，`d` 本身是否为交易日不影响）。

    日期越出快照覆盖区间抛 `CalendarOutOfCoverage`，快照未就绪抛
    `CalendarUnavailable`；不跨区间猜测，也不无限向后找。
    """
    return _shift(d, 1)


def prev_trading_day(d: date) -> date:
    """`d` 之前的最后一个交易日（严格小于 `d`）。

    存量订单回填要用它把 `confirm_date` 反推回受理日（T），这是项目里唯一
    的「向前找交易日」入口；越界与未就绪的失败语义同 `next_trading_day`。
    """
    return _shift(d, -1)


def _shift(d: date, step: int) -> date:
    """逐日推进直到落在交易日上；区间检查用快照边界，不靠 `is_trading_day` 抛错。"""
    snap = get_calendar_cache().snapshot
    if snap is None:
        raise CalendarUnavailable("交易日历未载入，无法推算交易日")

    cursor = d
    # 上限 60 天：超过说明快照有洞（整年数据缺失），继续循环只会空转
    for _ in range(60):
        cursor += timedelta(days=step)
        if cursor < snap.coverage_start or cursor > snap.coverage_end:
            raise CalendarOutOfCoverage(cursor, snap.coverage_start, snap.coverage_end)
        if cursor in snap.trading_days:
            return cursor
    raise CalendarOutOfCoverage(cursor, snap.coverage_start, snap.coverage_end)


def is_trading_time(dt: datetime) -> bool:
    """是否为 A 股连续竞价时段（交易日 9:30-15:00；含 9:30，不含 15:00）。

    dt 应为北京时间；带时区的值会先换算成北京时间，naive 值视为已是北京时间。
    日历不可用或日期越界时抛错，不返回 `False`。
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(BEIJING_TZ)
    if not is_trading_day(dt.date()):
        return False
    return (9, 30) <= (dt.hour, dt.minute) < (15, 0)
