"""交易日历两源（新浪交易日历 / 上证指数日 K）单元测试。

模块名称：server/sources/sina_trade_date.py、server/sources/sina_index_daily.py
所测功能：akshare DataFrame → `CalendarData` 的归一化、覆盖区间、
         空数据/行数偏少/结构异常的失败分类、超时包装的调用参数。
测试方法：`FakeFrame` 注入录制样本，`monkeypatch` 替换 akshare 超时包装；
         不导入 akshare、不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §6.2（同域名双源只作解析冗余）。
"""
from datetime import date, datetime

import pytest

from server.sources import sina_index_daily, sina_trade_date
from server.sources.models import FailureKind, SourceError


class FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        for index, row in enumerate(self._rows):
            yield index, row


class BrokenFrame:
    empty = False

    def iterrows(self):
        raise RuntimeError("DataFrame 结构变了")


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== 交易日历：正常数据 ====================


def test_trade_date解析字符串与date混合并给出覆盖区间(monkeypatch):
    monkeypatch.setattr(sina_trade_date, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame(
        [
            {"trade_date": "2026-01-05"},
            {"trade_date": date(2026, 1, 6)},
            {"trade_date": "not-a-date"},
        ]
    )

    data = sina_trade_date.parse_trade_date_frame(frame, "sina_trade_date")

    assert data.trading_days == frozenset({date(2026, 1, 5), date(2026, 1, 6)})
    assert data.coverage_start == date(2026, 1, 5)
    assert data.coverage_end == date(2026, 1, 6)
    assert data.source == "sina_trade_date"


def test_trade_date兼容datetime列(monkeypatch):
    monkeypatch.setattr(sina_trade_date, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame(
        [
            {"trade_date": datetime(2026, 1, 5, 0, 0)},
            {"trade_date": datetime(2026, 1, 6, 0, 0)},
        ]
    )

    data = sina_trade_date.parse_trade_date_frame(frame, "sina_trade_date")

    assert data.trading_days == frozenset({date(2026, 1, 5), date(2026, 1, 6)})


# ==================== 交易日历：异常 / 边界 ====================


def test_trade_date为空记EMPTY_PAYLOAD():
    with pytest.raises(SourceError) as excinfo:
        sina_trade_date.parse_trade_date_frame(FakeFrame([]), "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_trade_date行数明显偏少记SCHEMA_DRIFT():
    frame = FakeFrame([{"trade_date": "2026-01-05"}])

    with pytest.raises(SourceError) as excinfo:
        sina_trade_date.parse_trade_date_frame(frame, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_trade_date结构异常记PARSE_ERROR():
    with pytest.raises(SourceError) as excinfo:
        sina_trade_date.parse_trade_date_frame(BrokenFrame(), "s")

    assert _kind(excinfo) == FailureKind.PARSE_ERROR


# ==================== 指数日 K：正常数据 ====================


def test_index_daily用date列反推交易日(monkeypatch):
    monkeypatch.setattr(sina_index_daily, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame(
        [
            {"date": "2026-01-05", "close": 3000},
            {"date": "2026-01-06", "close": 3010},
        ]
    )

    data = sina_index_daily.parse_index_daily_frame(frame, "sina_index_daily")

    assert data.trading_days == frozenset({date(2026, 1, 5), date(2026, 1, 6)})
    assert data.coverage_end == date(2026, 1, 6)


def test_index_daily兼容datetime列(monkeypatch):
    monkeypatch.setattr(sina_index_daily, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame(
        [
            {"date": datetime(2026, 2, 2), "close": 3200},
            {"date": datetime(2026, 2, 3), "close": 3210},
        ]
    )

    data = sina_index_daily.parse_index_daily_frame(frame, "sina_index_daily")

    assert data.trading_days == frozenset({date(2026, 2, 2), date(2026, 2, 3)})


# ==================== 指数日 K：异常 / 边界 ====================


def test_index_daily为空记EMPTY_PAYLOAD():
    with pytest.raises(SourceError) as excinfo:
        sina_index_daily.parse_index_daily_frame(FakeFrame([]), "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_index_daily行数明显偏少记SCHEMA_DRIFT():
    frame = FakeFrame([{"date": "2026-01-05"}])

    with pytest.raises(SourceError) as excinfo:
        sina_index_daily.parse_index_daily_frame(frame, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


# ==================== 源类：超时包装参数 ====================


def test_trade_date源经超时包装调用(monkeypatch):
    calls = {}

    def fake_run(source_name, timeout, func):
        calls.update(source_name=source_name, timeout=timeout, func=func)
        return FakeFrame(
            [{"trade_date": "2026-01-05"}, {"trade_date": "2026-01-06"}]
        )

    monkeypatch.setattr(sina_trade_date, "run_akshare_with_timeout", fake_run)
    monkeypatch.setattr(sina_trade_date, "MIN_TRADING_DAYS", 2)

    data = sina_trade_date.SinaTradeDateSource().fetch_calendar()

    assert calls["source_name"] == "sina_trade_date"
    assert calls["timeout"] == 15.0
    assert callable(calls["func"])
    assert data.source == "sina_trade_date"


def test_index_daily源经超时包装调用(monkeypatch):
    calls = {}

    def fake_run(source_name, timeout, func):
        calls.update(source_name=source_name, timeout=timeout, func=func)
        return FakeFrame([{"date": "2026-01-05"}, {"date": "2026-01-06"}])

    monkeypatch.setattr(sina_index_daily, "run_akshare_with_timeout", fake_run)
    monkeypatch.setattr(sina_index_daily, "MIN_TRADING_DAYS", 2)

    data = sina_index_daily.SinaIndexDailySource().fetch_calendar()

    assert calls["source_name"] == "sina_index_daily"
    assert calls["timeout"] == 15.0
    assert data.source == "sina_index_daily"
