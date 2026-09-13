"""spot_cache_scheduler 单元测试：交易时段判断。

模块名称：server/services/spot_cache_scheduler.py
所测功能：_is_trading_time（A 股交易时段 9:30-15:00、工作日、北京时间）
测试方法：monkeypatch datetime.datetime.now 固定「当前时刻」，纯函数直测，不联网、不连 Supabase。
"""
import datetime as _dt

from server.services.spot_cache_scheduler import _is_trading_time

_RealDateTime = _dt.datetime  # 捕获原始 datetime 类，避免被 monkeypatch 影响


class _FrozenDateTime(_RealDateTime):
    """now() 返回固定时刻的 datetime 替身。"""

    now_value = _RealDateTime(2026, 1, 5, 10, 0, 0)  # 2026-01-05 是周一

    @classmethod
    def now(cls, tz=None):
        return cls.now_value


def _freeze(monkeypatch, year, month, day, hour, minute):
    _FrozenDateTime.now_value = _RealDateTime(year, month, day, hour, minute)
    monkeypatch.setattr("datetime.datetime", _FrozenDateTime)


def test_工作日盘中_为交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 5, 10, 0)  # 周一 10:00
    assert _is_trading_time() is True


def test_恰好开盘9点30_为交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 5, 9, 30)
    assert _is_trading_time() is True


def test_开盘前9点29_非交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 5, 9, 29)
    assert _is_trading_time() is False


def test_收盘前14点59_为交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 5, 14, 59)
    assert _is_trading_time() is True


def test_恰好收盘15点00_非交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 5, 15, 0)
    assert _is_trading_time() is False


def test_周六_非交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 10, 10, 0)  # 2026-01-10 是周六
    assert _is_trading_time() is False


def test_周日_非交易时段(monkeypatch):
    _freeze(monkeypatch, 2026, 1, 11, 10, 0)  # 2026-01-11 是周日
    assert _is_trading_time() is False
