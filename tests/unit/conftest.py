"""单元测试公共夹具。

交易日历（server/services/trading_calendar.py）是**模块级当日缓存**：一天只抓一次，
之后当天所有调用都走缓存。缓存若不在用例之间清空，前一个用例打桩的日历会漏给
后面的用例 —— 例如 test_portfolio_service 里的日历用例都涉及 2026-01-05，
一个脏缓存足以让断言全部失真。所以这里统一在每个用例前后清空。

同时提供 akshare 交易日历替身（`交易日历`）与「当前北京时间」固定器（`固定北京时间`），
凡需要假装「某天是/不是交易日」「现在几点」的用例都可直接用（当前由
test_trading_calendar.py 使用）。
"""
import sys
import types

import pytest

from server.services import trading_calendar


@pytest.fixture(autouse=True)
def _重置交易日历缓存():
    trading_calendar.reset_cache()
    yield
    trading_calendar.reset_cache()


class _FakeCalendarFrame:
    """模拟 akshare.tool_trade_date_hist_sina() 的返回值（支持 iterrows + 下标取值）。"""

    def __init__(self, trade_dates):
        self._rows = [{"trade_date": d} for d in trade_dates]

    def iterrows(self):
        for i, row in enumerate(self._rows):
            yield i, row


class TradingCalendarStub:
    """akshare 交易日历替身：可设日期、可设故障、可统计抓取次数。

    用法：
        交易日历.use(["2026-01-05"])   # 日历里只有这一天
        交易日历.fail()                # 数据源抛异常
        assert 交易日历.calls == 1     # 抓取被调用的次数
    """

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self._dates = []
        self._broken = False
        self._installed = False
        self.calls = 0

    def use(self, trade_dates):
        """让日历返回给定日期（ISO 字符串列表）。"""
        self._dates = list(trade_dates)
        self._broken = False
        self._install()

    def fail(self):
        """让日历抓取抛异常。"""
        self._dates = []
        self._broken = True
        self._install()

    def _install(self):
        if self._installed:
            return
        stub = self

        def _fetch():
            stub.calls += 1
            if stub._broken:
                raise RuntimeError("交易日历数据源不可用")
            return _FakeCalendarFrame(stub._dates)

        module = types.ModuleType("akshare")
        module.tool_trade_date_hist_sina = _fetch
        self._monkeypatch.setitem(sys.modules, "akshare", module)
        # 注入后清空缓存：保证本用例从干净状态开始，且用上刚注入的替身
        trading_calendar.reset_cache()
        self._installed = True


@pytest.fixture
def 交易日历(monkeypatch):
    return TradingCalendarStub(monkeypatch)


@pytest.fixture
def 固定北京时间(monkeypatch):
    """固定 trading_calendar.beijing_now() 的返回值。"""

    def _freeze(year, month, day, hour=0, minute=0):
        fixed = trading_calendar.datetime(
            year, month, day, hour, minute, tzinfo=trading_calendar.BEIJING_TZ
        )
        monkeypatch.setattr(trading_calendar, "beijing_now", lambda: fixed)
        return fixed

    return _freeze
