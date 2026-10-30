"""trading_calendar 单元测试：DB 快照语义与「无兜底」错误行为。

模块名称：server/services/trading_calendar.py
所测功能：is_trading_day / is_trading_time / calendar_status / reset_cache
测试方法：直接注入假快照（install_snapshot），不联网、不连 Supabase。
"""
from datetime import date, datetime, timezone

import pytest

from server.services import trading_calendar as tc
from server.services.trading_calendar_cache import (
    CalendarOutOfCoverage,
    CalendarStatus,
    CalendarUnavailable,
)

北京 = tc.BEIJING_TZ


def _注入(days, start=None, end=None):
    """注入交易日集合；默认覆盖区间取 min/max，必要时显式放宽。"""
    tc.install_snapshot(days, coverage_start=start, coverage_end=end)


def _北京时刻(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=北京)


# ==================== is_trading_day ====================


def test_交易日_命中快照():
    _注入(["2026-01-05", "2026-01-06"])
    assert tc.is_trading_day(date(2026, 1, 5)) is True


def test_区间内周末_为非交易日():
    _注入(["2026-01-05"], start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert tc.is_trading_day(date(2026, 1, 10)) is False  # 周六
    assert tc.is_trading_day(date(2026, 1, 11)) is False  # 周日


def test_法定节假日_即使工作日也不是交易日():
    """2026-10-01 是周四，但属国庆假期 —— 这是无兜底后仍必须答对的场景。"""
    _注入(["2026-09-30", "2026-10-09"], start=date(2026, 9, 1), end=date(2026, 10, 31))
    assert date(2026, 10, 1).weekday() == 3
    assert tc.is_trading_day(date(2026, 10, 1)) is False


def test_快照未载入_抛CalendarUnavailable():
    """不返回 False，也不按星期几猜。"""
    with pytest.raises(CalendarUnavailable):
        tc.is_trading_day(date(2026, 1, 5))


def test_早于覆盖区间_抛CalendarOutOfCoverage():
    _注入(["2026-01-05"])
    with pytest.raises(CalendarOutOfCoverage) as exc:
        tc.is_trading_day(date(2026, 1, 4))
    assert "2026-01-04" in str(exc.value)
    assert "2026-01-05" in str(exc.value)


def test_晚于覆盖区间_抛CalendarOutOfCoverage():
    _注入(["2026-01-05"])
    with pytest.raises(CalendarOutOfCoverage):
        tc.is_trading_day(date(2026, 1, 6))


def test_calendar_status_四态():
    _注入(["2026-01-05"], start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert tc.calendar_status(date(2026, 1, 5)) is CalendarStatus.TRADING
    assert tc.calendar_status(date(2026, 1, 10)) is CalendarStatus.NON_TRADING
    assert tc.calendar_status(date(2025, 12, 31)) is CalendarStatus.OUT_OF_COVERAGE
    tc.reset_cache()
    assert tc.calendar_status(date(2026, 1, 5)) is CalendarStatus.UNAVAILABLE


def test_reset_cache后重新变为不可用():
    _注入(["2026-01-05"])
    tc.reset_cache()
    with pytest.raises(CalendarUnavailable):
        tc.is_trading_day(date(2026, 1, 5))


# ==================== is_trading_time：时段边界 ====================


@pytest.fixture
def 交易日快照():
    _注入(["2026-01-05"], start=date(2026, 1, 1), end=date(2026, 1, 31))


def test_交易日盘中_为交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 10, 0)) is True


def test_恰好开盘930_为交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 9, 30)) is True


def test_开盘前929_非交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 9, 29)) is False


def test_收盘前1459_为交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 14, 59)) is True


def test_恰好收盘1500_非交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 15, 0)) is False


def test_午夜零点_非交易时段(交易日快照):
    assert tc.is_trading_time(_北京时刻(2026, 1, 5, 0, 0)) is False


def test_带时区的非北京时刻_先换算再判断(交易日快照):
    """UTC 01:30 = 北京 09:30，恰好开盘。"""
    assert tc.is_trading_time(datetime(2026, 1, 5, 1, 30, tzinfo=timezone.utc)) is True
    assert tc.is_trading_time(datetime(2026, 1, 5, 1, 29, tzinfo=timezone.utc)) is False


def test_naive时刻_视为已是北京时间(交易日快照):
    assert tc.is_trading_time(datetime(2026, 1, 5, 10, 0)) is True


def test_区间内非交易日盘中_非交易时段():
    _注入(["2026-09-30", "2026-10-09"], start=date(2026, 9, 1), end=date(2026, 10, 31))
    assert tc.is_trading_time(_北京时刻(2026, 10, 1, 10, 0)) is False


def test_日期越界_抛错而不是返回False():
    _注入(["2026-01-05"])
    with pytest.raises(CalendarOutOfCoverage):
        tc.is_trading_time(_北京时刻(2026, 1, 6, 10, 0))


def test_快照未载入_时段判断抛CalendarUnavailable():
    with pytest.raises(CalendarUnavailable):
        tc.is_trading_time(_北京时刻(2026, 1, 5, 10, 0))
