"""trading_calendar 单元测试：A 股交易日历（全项目唯一来源）。

模块名称：server/services/trading_calendar.py
所测功能：is_trading_day / is_trading_time / beijing_now、日历缓存与失败降级
测试方法：注入 akshare 日历替身（见 tests/unit/conftest.py）+ 固定「当前北京时间」，
         纯函数直测，不联网、不连 Supabase。
"""
from datetime import date, datetime, timezone

import pytest

from server.services import trading_calendar as tc


def _北京(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=tc.BEIJING_TZ)


# ==================== is_trading_day：真实日历 ====================


def test_交易日_命中日历(交易日历):
    交易日历.use(["2026-01-05", "2026-01-06"])
    assert tc.is_trading_day(date(2026, 1, 5)) is True
    assert 交易日历.calls == 1


def test_非交易日_日历未命中(交易日历):
    交易日历.use(["2026-01-05", "2026-01-06"])
    assert tc.is_trading_day(date(2026, 1, 10)) is False  # 周六
    assert tc.is_trading_day(date(2026, 1, 11)) is False  # 周日


def test_法定节假日_即使工作日也不是交易日(交易日历):
    """2026-10-01 是周四，但属国庆假期 —— 这是修复的核心场景。"""
    交易日历.use(["2026-09-30", "2026-10-09"])  # 假期前后两个交易日，中间整段休市
    assert date(2026, 10, 1).weekday() == 3  # 先确认当天确实是周四（工作日）
    assert tc.is_trading_day(date(2026, 10, 1)) is False


def test_周末_不是交易日(交易日历):
    """周末即使被国家安排为调休补班日也不开市 —— 交易日只认日历。"""
    交易日历.use(["2026-10-09"])  # 2026-10-10 是周六，日历里没有
    assert date(2026, 10, 10).weekday() == 5
    assert tc.is_trading_day(date(2026, 10, 10)) is False


def test_日历含异常日期_跳过该行不影响其余(交易日历):
    交易日历.use(["2026-01-05", "not-a-date"])
    assert tc.is_trading_day(date(2026, 1, 5)) is True


# ==================== is_trading_time：时段边界 ====================


def test_交易日盘中_为交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 10, 0)) is True


def test_恰好开盘930_为交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 9, 30)) is True


def test_开盘前929_非交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 9, 29)) is False


def test_收盘前1459_为交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 14, 59)) is True


def test_恰好收盘1500_非交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 15, 0)) is False


def test_午夜零点_非交易时段(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(_北京(2026, 1, 5, 0, 0)) is False


def test_法定节假日盘中_非交易时段(交易日历):
    交易日历.use(["2026-09-30", "2026-10-09"])
    assert tc.is_trading_time(_北京(2026, 10, 1, 10, 0)) is False


def test_带时区的非北京时刻_先换算再判断(交易日历):
    """UTC 01:30 = 北京 09:30，恰好开盘。"""
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(datetime(2026, 1, 5, 1, 30, tzinfo=timezone.utc)) is True
    assert tc.is_trading_time(datetime(2026, 1, 5, 1, 29, tzinfo=timezone.utc)) is False


def test_naive时刻_视为已是北京时间(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_time(datetime(2026, 1, 5, 10, 0)) is True


# ==================== 缓存：一天只抓一次 ====================


def test_同一天多次判断_只抓一次日历(交易日历):
    交易日历.use(["2026-01-05"])
    for _ in range(5):
        assert tc.is_trading_day(date(2026, 1, 5)) is True
        assert tc.is_trading_time(_北京(2026, 1, 5, 10, 0)) is True
    assert 交易日历.calls == 1


def test_隔天重新抓取日历(交易日历, 固定北京时间):
    交易日历.use(["2026-01-05", "2026-01-06"])
    固定北京时间(2026, 1, 5, 10, 0)
    assert tc.is_trading_day(date(2026, 1, 5)) is True

    固定北京时间(2026, 1, 6, 10, 0)
    assert tc.is_trading_day(date(2026, 1, 6)) is True
    assert 交易日历.calls == 2


def test_reset_cache后重新抓取(交易日历):
    交易日历.use(["2026-01-05"])
    assert tc.is_trading_day(date(2026, 1, 5)) is True
    tc.reset_cache()
    assert tc.is_trading_day(date(2026, 1, 5)) is True
    assert 交易日历.calls == 2


# ==================== 失败降级 ====================


def test_从未取到日历_退化为工作日判断(交易日历):
    """数据源从未成功过时的兜底 —— 与修复前的行为一致，不会因抖动把交易日判成休市。"""
    交易日历.fail()
    assert tc.is_trading_day(date(2026, 1, 5)) is True   # 周一
    assert tc.is_trading_day(date(2026, 1, 10)) is False  # 周六


def test_日历返回空_退化为工作日判断(交易日历):
    交易日历.use([])
    assert tc.is_trading_day(date(2026, 1, 5)) is True


def test_抓取失败_沿用上次成功副本(交易日历, 固定北京时间):
    交易日历.use(["2026-01-05"])
    固定北京时间(2026, 1, 5, 10, 0)
    assert tc.is_trading_day(date(2026, 1, 5)) is True

    # 第二天数据源挂了
    固定北京时间(2026, 1, 6, 10, 0)
    交易日历.fail()

    # 旧副本里没有 2026-01-07（周三）：若退化成「工作日即交易日」这里会是 True
    assert tc.is_trading_day(date(2026, 1, 7)) is False
    assert 交易日历.calls == 2  # 失败时仍会重试，只是结果退回旧副本


def test_抓取失败_不推进缓存日期_下次仍会重试(交易日历, 固定北京时间):
    交易日历.use(["2026-01-05"])
    固定北京时间(2026, 1, 5, 10, 0)
    assert tc.is_trading_day(date(2026, 1, 5)) is True

    固定北京时间(2026, 1, 6, 10, 0)
    交易日历.fail()
    tc.is_trading_day(date(2026, 1, 6))
    tc.is_trading_day(date(2026, 1, 6))
    # 1 次（01-05 成功）+ 2 次（01-06 失败且缓存日期未推进 —— 每次调用都重试，而不是缓存住失败）
    assert 交易日历.calls == 3


# ==================== beijing_now ====================


def test_beijing_now_带北京时区():
    now = tc.beijing_now()
    assert now.utcoffset() == tc.BEIJING_TZ.utcoffset(None)
