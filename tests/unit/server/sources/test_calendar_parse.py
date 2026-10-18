"""交易日历源解析单测（内嵌 DataFrame 替身，不联网）。"""
from datetime import date

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


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


def test_trade_date解析并给出覆盖区间(monkeypatch):
    monkeypatch.setattr(sina_trade_date, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame([
        {"trade_date": "2026-01-05"},
        {"trade_date": date(2026, 1, 6)},
        {"trade_date": "not-a-date"},
    ])

    data = sina_trade_date.parse_trade_date_frame(frame, "s")

    assert data.trading_days == frozenset({date(2026, 1, 5), date(2026, 1, 6)})
    assert data.coverage_start == date(2026, 1, 5)
    assert data.coverage_end == date(2026, 1, 6)


def test_trade_date为空记EMPTY_PAYLOAD():
    with pytest.raises(SourceError) as excinfo:
        sina_trade_date.parse_trade_date_frame(FakeFrame([]), "s")
    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_trade_date行数明显偏少记SCHEMA_DRIFT():
    frame = FakeFrame([{"trade_date": "2026-01-05"}])
    with pytest.raises(SourceError) as excinfo:
        sina_trade_date.parse_trade_date_frame(frame, "s")
    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_index_daily用date列反推交易日(monkeypatch):
    monkeypatch.setattr(sina_index_daily, "MIN_TRADING_DAYS", 2)
    frame = FakeFrame([
        {"date": "2026-01-05", "close": 3000},
        {"date": "2026-01-06", "close": 3010},
    ])

    data = sina_index_daily.parse_index_daily_frame(frame, "s")

    assert data.trading_days == frozenset({date(2026, 1, 5), date(2026, 1, 6)})
    assert data.coverage_end == date(2026, 1, 6)
