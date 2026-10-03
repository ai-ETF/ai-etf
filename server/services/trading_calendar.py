"""A 股交易日历（全项目唯一来源）

原先「是不是交易日」有两套实现，且互不一致：

    函数 | 位置 | 判断依据 | 认节假日
    _is_trading_day  | portfolio_service | akshare 真实交易日历 | ✅
    _is_trading_time | spot_cache_scheduler | 工作日 + 9:30-15:00 | ❌

后者在**法定节假日里的工作日**（如国庆 10/1 恰逢周四）会判成交易时段，
行情缓存在休市日仍每 30 秒刷一次。本模块把日历收敛到一处：

- `spot_cache_scheduler._is_trading_time()` **已删除**（只剩
  `finance_api_service.refresh_spot_cache()` 一处调用，留同名包装没有意义），
  改为直接调用本模块的 `is_trading_time(beijing_now())`；
- `PortfolioService._is_trading_day()` 保留为**委托**本模块的一层薄封装
  （多处调用 + 多处测试打桩，是 T 日口径的稳定接缝）。

性能：`_is_trading_day` 原先每次调用都请求一次新浪交易日历，而
`_next_trading_day` 是在循环里调它的（一次最多 14 次网络请求），
`apply_purchase` 又会调用多次 `_next_trading_day`。本模块按北京日期缓存整份日历 ——
日历是覆盖全年的静态数据，一天取一次足够；抓取失败时沿用上一次成功的副本，
而不是立刻退化成「按星期几猜」。
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Set

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 当日缓存：{"day": 抓取当日（北京日期）, "dates": 交易日集合 | None}
# dates 为 None 表示**从未成功取到过**日历，此时退化为「工作日即交易日」
_cache: dict = {"day": None, "dates": None}


def beijing_now() -> datetime:
    """当前北京时间（带时区）"""
    return datetime.now(BEIJING_TZ)


def reset_cache():
    """清空日历缓存。

    测试专用：日历是模块级缓存，不清空会让用例之间互相污染
    （前一个用例 stub 的日历会漏给下一个用例）。
    """
    _cache["day"] = None
    _cache["dates"] = None


def _fetch_calendar() -> Optional[Set[date]]:
    """请求新浪交易日历，返回全年交易日集合；失败或为空返回 None。"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = set()
        for _, row in df.iterrows():
            try:
                dates.add(date.fromisoformat(str(row["trade_date"])))
            except ValueError:
                continue
        return dates or None
    except Exception as e:
        logger.warning(f"获取交易日历失败，将沿用上次结果: {e}")
        return None


def _trading_dates() -> Optional[Set[date]]:
    """交易日集合（按北京日期缓存，一天最多请求一次）。从未成功取到过时返回 None。"""
    today = beijing_now().date()
    if _cache["day"] == today:
        return _cache["dates"]

    dates = _fetch_calendar()
    if dates is None:
        # 抓取失败：保留上一次成功的副本（日历覆盖全年，旧副本通常仍然有效），
        # 且**不更新 day** —— 下次调用会重试。从未成功过则 dates 仍为 None。
        return _cache["dates"]

    _cache["day"] = today
    _cache["dates"] = dates
    return dates


def is_trading_day(d: date) -> bool:
    """是否为 A 股交易日。

    取不到日历（数据源从未成功过）时退化为「周一至周五」—— 与修复前的行为一致：
    宁可多刷几次行情，也不要因为数据源抖动把交易日误判成休市。
    """
    dates = _trading_dates()
    if dates is None:
        return d.weekday() < 5
    return d in dates


def is_trading_time(dt: datetime) -> bool:
    """是否为 A 股连续竞价时段（交易日 9:30-15:00；含 9:30，不含 15:00）。

    dt 应为北京时间；带时区的值会先换算成北京时间，naive 值视为已是北京时间。
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(BEIJING_TZ)
    if not is_trading_day(dt.date()):
        return False
    return (9, 30) <= (dt.hour, dt.minute) < (15, 0)
