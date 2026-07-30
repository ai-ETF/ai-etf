"""
A股交易日历工具

通过 akshare 动态拉取 A 股交易日历，无需手动维护节假日。
首次初始化时自动加载，之后缓存到内存。

数据来源：新浪财经交易日历（akshare.tool_trade_date_hist_sina）

提供：
- 判断某天是否为 A 股交易日
- 获取下一个交易日
- 判断是否在交易时间（场外基金 15:00 截止 / 场内 ETF 9:30-15:00）
"""

import logging
import time
from datetime import date, datetime, timedelta, time as dt_time

logger = logging.getLogger(__name__)

# 交易日集合（date 对象），O(1) 查找
_TRADING_DAYS: set[date] = set()
_initialized = False


def _load_trading_calendar():
    """从 akshare 拉取 A 股交易日历，构建哈希表"""
    global _TRADING_DAYS, _initialized
    if _initialized:
        return

    try:
        import akshare as ak
        logger.info("正在从 akshare 加载 A 股交易日历...")
        df = ak.tool_trade_date_hist_sina()
        for _, row in df.iterrows():
            d_str = str(row['trade_date'])
            try:
                _TRADING_DAYS.add(date.fromisoformat(d_str))
            except ValueError:
                pass
        _initialized = True
        logger.info(f"A 股交易日历加载完成，共 {len(_TRADING_DAYS)} 个交易日")
        if _TRADING_DAYS:
            sorted_days = sorted(_TRADING_DAYS)
            logger.info(f"交易日范围: {sorted_days[0]} ~ {sorted_days[-1]}")
    except Exception as e:
        logger.error(f"加载交易日历失败: {e}，将使用工作日判断（无节假日过滤）")
        _initialized = True  # 标记已初始化，不再重试


def is_trading_day(d: date) -> bool:
    """
    判断是否为 A 股交易日。

    基于 akshare 拉取的交易日历，涵盖周末和法定节假日。
    """
    _load_trading_calendar()
    return d in _TRADING_DAYS


def next_trading_day(d: date) -> date:
    """
    获取下一个交易日（含当天，如果当天是交易日则返回当天）。
    """
    if is_trading_day(d):
        return d
    d = d + timedelta(days=1)
    # 防止死循环：最多找 30 天
    for _ in range(30):
        if is_trading_day(d):
            return d
        d = d + timedelta(days=1)
    logger.warning(f"未能在 30 天内找到下一个交易日，返回 {d}")
    return d


def prev_trading_day(d: date) -> date:
    """获取上一个交易日（不含当天）"""
    d = d - timedelta(days=1)
    for _ in range(30):
        if is_trading_day(d):
            return d
        d = d - timedelta(days=1)
    return d


def is_before_cutoff(dt: datetime) -> bool:
    """
    判断是否在场外基金交易截止时间（15:00）之前。

    15:00 前的订单按当日净值确认，15:00 后顺延到下一个交易日。
    """
    return dt.hour < 15


def get_confirmation_date(submit_time: datetime) -> date:
    """
    获取场外基金订单的确认日期（净值日期）。

    规则：
    - 交易日 15:00 前提交 → 当日（T日）净值确认
    - 交易日 15:00 后提交 → 下一个交易日净值确认
    - 非交易日提交 → 下一个交易日净值确认

    返回: 确认日期的 date 对象
    """
    submit_date = submit_time.date()

    if not is_trading_day(submit_date):
        return next_trading_day(submit_date)

    if is_before_cutoff(submit_time):
        return submit_date
    else:
        return next_trading_day(submit_date + timedelta(days=1))


def is_order_pending(submit_time: datetime) -> bool:
    """
    判断订单是否需要延迟确认。

    如果当前不在交易日或已过 15:00，订单需要等待到下一个交易日才确认。

    返回: True 表示订单待确认（延迟），False 表示可以立即确认
    """
    now_date = submit_time.date()
    if not is_trading_day(now_date):
        return True
    if not is_before_cutoff(submit_time):
        return True
    return False


# ==================== ETF 场内交易时段 ====================


def is_etf_trading_time(dt: datetime) -> bool:
    """
    判断是否在 ETF 场内交易时段。

    ETF 交易时段：
    - 上午：9:30-11:30
    - 下午：13:00-15:00
    - 必须是交易日

    返回: True 表示当前可以交易 ETF
    """
    if not is_trading_day(dt.date()):
        return False
    t = dt.time()
    morning = dt_time(9, 30) <= t <= dt_time(11, 30)
    afternoon = dt_time(13, 0) <= t <= dt_time(15, 0)
    return morning or afternoon
