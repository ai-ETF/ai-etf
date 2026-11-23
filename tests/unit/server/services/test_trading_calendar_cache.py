"""TradingCalendarCache：启动载入、刷新校验、dry_run、事务性写入与 diff。

模块名称：server/services/trading_calendar_cache.py
所测功能：load_from_db / refresh / _validate / _diff_rows / describe
测试方法：假 Supabase 客户端 + 假 SourceRouter；不联网、不连 Supabase。
"""
from datetime import date, datetime, timedelta

import pytest

from server.services import trading_calendar_cache as tcc
from server.services.trading_calendar_cache import (
    BEIJING_TZ,
    CalendarDataInvalid,
    CalendarRefreshTimeout,
    CalendarUnavailable,
    RefreshInProgress,
    TradingCalendarCache,
    _diff_rows,
    _expand_natural_days,
)
from server.sources.models import AllSourcesFailed, CalendarData

# 源当前实际覆盖（数据组 A，见测试文档 §测试数据集）
REAL_START = date(1990, 12, 19)
REAL_END = date(2026, 12, 31)
# 2026 国庆假期（10/3、10/4 本就是周末，不重复列）
NATIONAL_DAY_2026 = {date(2026, 10, d) for d in (1, 2, 5, 6, 7)}


# ==================== 替身 ====================


class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data if data is not None else []
        self.count = count


class _Query:
    """按表名返回预设行；支持 select / eq / order / limit / range / upsert。"""

    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.filters = []
        self.offset = 0
        self._limit = 1000
        self.head = False
        self.upsert_payload = None

    def select(self, columns, count=None, head=False):
        self.head = head
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, column):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self.offset = start
        self._limit = end - start + 1
        return self

    def upsert(self, payload, on_conflict=None):
        self.upsert_payload = payload
        return self

    def execute(self):
        if self.client.fail:
            raise RuntimeError("DB 连接失败")
        if self.upsert_payload is not None:
            self.client.upserts.append((self.table_name, self.upsert_payload))
            return _Resp()
        if self.table_name == "trading_calendar_state":
            return _Resp(self.client.state_rows[:1])

        rows = self.client.trading_rows
        if ("is_trading_day", True) in self.filters:
            rows = [r for r in rows if r["is_trading_day"]]
        if self.head:
            return _Resp(count=len(rows))
        return _Resp(rows[self.offset:self.offset + self._limit])


class _Rpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _Resp(self.data)


class _FakeClient:
    """假 Supabase 客户端：按表返回预设行，RPC 记录调用并模拟整表替换。"""

    def __init__(self, state_rows=None, trading_rows=None, fail=False):
        self.state_rows = state_rows or []
        self.trading_rows = list(trading_rows or [])
        self.fail = fail
        self.upserts = []
        self.rpc_calls = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        if name == "replace_trading_calendar":
            # 模拟数据库函数：交易日展开成自然日，整表替换。
            days = {date.fromisoformat(d) for d in params["p_trading_days"]}
            if days:
                rows = []
                current = min(days)
                while current <= max(days):
                    rows.append({"trade_date": current, "is_trading_day": current in days})
                    current += timedelta(days=1)
                self.trading_rows = rows
        return _Rpc({"ok": True})


class _BrokenRpcClient(_FakeClient):
    def rpc(self, name, params):
        raise RuntimeError("RPC 执行失败")


class _FakeRouter:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.calls = 0

    def fetch_calendar(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.data


# ==================== 数据 ====================


def _weekdays(start, end, holidays=()):
    days = set()
    current = start
    while current <= end:
        if current.weekday() < 5 and current not in holidays:
            days.add(current)
        current += timedelta(days=1)
    return frozenset(days)


def _last_n_weekdays(end, n):
    """从 end 往前取 n 个工作日（用于构造最小交易日数边界）。"""
    days = set()
    current = end
    while len(days) < n:
        if current.weekday() < 5:
            days.add(current)
        current -= timedelta(days=1)
    return frozenset(days)


def _calendar(start=REAL_START, end=REAL_END, holidays=NATIONAL_DAY_2026):
    """数据组 A：源真实形态（长区间、工作日、剔除国庆假期）。"""
    days = _weekdays(start, end, holidays)
    return CalendarData(days, start, end, "sina_trade_date")


def _snapshot_cache(data, client=None):
    return TradingCalendarCache(client=client or _FakeClient(), router=_FakeRouter(data))


# ==================== 启动载入 ====================


def test_启动载入_DB有数据_不触网且快照就绪():
    client = _FakeClient(
        state_rows=[{
            "coverage_start": "2026-01-01",
            "coverage_end": "2026-12-31",
            "last_error": None,
            "last_success_at": "2026-10-01T00:00:00+08:00",
        }],
        trading_rows=[
            {"trade_date": "2026-01-01", "is_trading_day": False},
            {"trade_date": "2026-01-05", "is_trading_day": True},
            {"trade_date": "2026-01-06", "is_trading_day": True},
        ],
    )
    router = _FakeRouter(error=AssertionError("启动载入不应访问上游"))
    cache = TradingCalendarCache(client=client, router=router)

    assert cache.load_from_db() is True
    assert cache.ready is True
    assert cache.is_trading_day(date(2026, 1, 5)) is True
    assert cache.is_trading_day(date(2026, 1, 1)) is False
    assert len(cache.snapshot.trading_days) == 2
    assert cache.snapshot.source == "db"
    assert router.calls == 0


def test_启动载入_DB为空_ready为False且错误带原因():
    router = _FakeRouter(error=AssertionError("启动载入不应访问上游"))
    cache = TradingCalendarCache(client=_FakeClient(), router=router)

    assert cache.load_from_db() is False
    assert cache.ready is False
    with pytest.raises(CalendarUnavailable) as exc:
        cache.is_trading_day(date(2026, 1, 5))
    assert "trading_calendar_state 为空" in str(exc.value)
    assert router.calls == 0


def test_启动载入_DB异常_进程不崩且带失败原因():
    router = _FakeRouter(error=AssertionError("启动载入不应访问上游"))
    cache = TradingCalendarCache(client=_FakeClient(fail=True), router=router)

    assert cache.load_from_db() is False
    assert cache.ready is False
    with pytest.raises(CalendarUnavailable) as exc:
        cache.is_trading_day(date(2026, 1, 5))
    assert "DB 连接失败" in str(exc.value)
    assert router.calls == 0


def test_启动载入_状态缺覆盖区间_视为不可用():
    client = _FakeClient(state_rows=[{"coverage_start": None, "coverage_end": None}])
    cache = TradingCalendarCache(client=client, router=_FakeRouter())

    assert cache.load_from_db() is False
    assert cache.ready is False


def test_启动载入_无交易日行_视为不可用():
    client = _FakeClient(state_rows=[{
        "coverage_start": "2026-01-01",
        "coverage_end": "2026-12-31",
    }])
    cache = TradingCalendarCache(client=client, router=_FakeRouter())

    assert cache.load_from_db() is False
    assert cache.ready is False


def test_启动载入_交易日超过1000行_分页读完():
    rows = [
        {"trade_date": date(2020, 1, 1) + timedelta(days=i), "is_trading_day": True}
        for i in range(1002)
    ]
    client = _FakeClient(
        state_rows=[{"coverage_start": "2020-01-01", "coverage_end": "2026-12-31"}],
        trading_rows=rows,
    )
    cache = TradingCalendarCache(client=client, router=_FakeRouter())

    assert cache.load_from_db() is True
    assert len(cache.snapshot.trading_days) == 1002


# ==================== 人工刷新 ====================


def test_dry_run_只算diff_不写库不替换内存():
    data = _calendar()
    client = _FakeClient()
    cache = _snapshot_cache(data, client)
    cache.install_snapshot(
        [date(2026, 1, 5)],
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 1, 31),
    )
    before = cache.snapshot

    result = cache.refresh(dry_run=True)

    assert result.dry_run is True
    assert result.stats["inserted"] == (REAL_END - REAL_START).days + 1
    assert cache.snapshot is before
    assert client.rpc_calls == []


def test_正式刷新_一次RPC并替换内存快照():
    data = _calendar()
    client = _FakeClient()
    cache = _snapshot_cache(data, client)

    result = cache.refresh()

    assert result.dry_run is False
    assert client.rpc_calls and client.rpc_calls[0][0] == "replace_trading_calendar"
    name, params = client.rpc_calls[0]
    assert params["p_source"] == "sina_trade_date"
    assert len(params["p_trading_days"]) == len(data.trading_days)
    assert cache.snapshot.trading_days == data.trading_days
    assert cache.is_trading_day(date(2026, 10, 1)) is False  # 国庆假期（周四）


def test_连续两次刷新_整表替换幂等():
    data = _calendar()
    client = _FakeClient()
    cache = _snapshot_cache(data, client)
    natural_days = (REAL_END - REAL_START).days + 1

    first = cache.refresh()
    second = cache.refresh()

    assert first.stats["inserted"] == natural_days
    assert second.stats == {
        "inserted": 0, "updated": 0, "unchanged": natural_days, "deleted": 0,
    }
    assert len(client.rpc_calls) == 2


def test_已有刷新在跑_再次调用抛RefreshInProgress():
    cache = _snapshot_cache(_calendar())
    assert cache._refresh_lock.acquire(blocking=False)
    try:
        with pytest.raises(RefreshInProgress):
            cache.refresh()
    finally:
        cache._refresh_lock.release()


def test_刷新超时_不写库不替换内存():
    data = _calendar()
    client = _FakeClient()
    cache = _snapshot_cache(data, client)

    class _Clock:
        def __init__(self):
            self.values = iter([0.0, 31.0, 31.0, 31.0])

        def monotonic(self):
            return next(self.values)

    original = tcc.time
    tcc.time = _Clock()
    try:
        with pytest.raises(CalendarRefreshTimeout):
            cache.refresh()
    finally:
        tcc.time = original

    assert client.rpc_calls == []
    assert cache.ready is False


def test_刷新失败_旧快照与内存原样保留():
    client = _FakeClient()
    error = AllSourcesFailed(
        "calendar", [{"source": "sina_trade_date", "kind": "TIMEOUT", "error": "超时"}]
    )
    cache = TradingCalendarCache(client=client, router=_FakeRouter(error=error))
    cache.install_snapshot(
        [date(2026, 1, 5)], coverage_start=date(2026, 1, 1), coverage_end=date(2026, 12, 31)
    )
    before = cache.snapshot

    with pytest.raises(AllSourcesFailed):
        cache.refresh()

    assert cache.snapshot is before
    assert "AllSourcesFailed" in cache.last_error
    assert client.upserts and "AllSourcesFailed" in client.upserts[0][1]["last_error"]


def test_写库失败_内存不替换():
    client = _BrokenRpcClient()
    cache = _snapshot_cache(_calendar(), client)

    with pytest.raises(RuntimeError, match="RPC 执行失败"):
        cache.refresh()

    assert cache.ready is False
    assert "RPC 执行失败" in cache.last_error


# ==================== 刷新前校验 ====================


def test_校验_空集合_拒绝刷新():
    data = CalendarData(frozenset(), REAL_START, REAL_END, "sina_trade_date")
    client = _FakeClient()
    cache = _snapshot_cache(data, client)

    with pytest.raises(CalendarDataInvalid, match="为空"):
        cache.refresh()
    assert cache.ready is False
    assert client.rpc_calls == []


def test_校验_交易日不足1000_拒绝刷新():
    days = _last_n_weekdays(REAL_END, 999)
    data = CalendarData(days, min(days), REAL_END, "sina_trade_date")
    cache = _snapshot_cache(data)

    with pytest.raises(CalendarDataInvalid, match="999"):
        cache.refresh()
    assert cache.ready is False


def test_校验_恰好1000个交易日_通过():
    days = _last_n_weekdays(REAL_END, 1000)
    data = CalendarData(days, min(days), REAL_END, "sina_trade_date")
    cache = _snapshot_cache(data)

    result = cache.refresh(dry_run=True)

    assert result.dry_run is True


def test_校验_覆盖区间倒置_拒绝刷新():
    days = _last_n_weekdays(REAL_END, 1000)
    data = CalendarData(days, REAL_END, min(days), "sina_trade_date")
    cache = _snapshot_cache(data)

    with pytest.raises(CalendarDataInvalid, match="覆盖区间非法"):
        cache.refresh()


def test_校验_覆盖终点早于今天_拒绝刷新():
    today = datetime.now(BEIJING_TZ).date()
    end = today - timedelta(days=1)
    days = _last_n_weekdays(end, 1200)
    data = CalendarData(days, min(days), end, "sina_trade_date")
    cache = _snapshot_cache(data)

    with pytest.raises(CalendarDataInvalid, match="早于今天"):
        cache.refresh()


def test_校验_覆盖终点等于今天_通过():
    today = datetime.now(BEIJING_TZ).date()
    days = _last_n_weekdays(today, 1000)
    data = CalendarData(days, min(days), today, "sina_trade_date")
    cache = _snapshot_cache(data)

    result = cache.refresh(dry_run=True)

    assert result.dry_run is True


# ==================== diff / 展开 ====================


def test_自然日展开_周末标为非交易日():
    data = CalendarData(
        frozenset({date(2026, 1, 1), date(2026, 1, 2)}),
        date(2026, 1, 1),
        date(2026, 1, 4),
        "sina_trade_date",
    )

    rows = _expand_natural_days(data)

    assert len(rows) == 4
    assert rows[date(2026, 1, 1)] is True
    assert rows[date(2026, 1, 2)] is True
    assert rows[date(2026, 1, 3)] is False
    assert rows[date(2026, 1, 4)] is False


def test_diff_区分新增_更新_删除_未变():
    existing = {
        date(2026, 1, 1): True,
        date(2026, 1, 2): True,
        date(2026, 1, 3): False,
    }
    new_rows = {
        date(2026, 1, 1): True,
        date(2026, 1, 2): False,
        date(2026, 1, 4): True,
    }

    stats, diff, truncated = _diff_rows(existing, new_rows)

    assert stats == {"inserted": 1, "updated": 1, "unchanged": 1, "deleted": 1}
    assert truncated is False
    assert {(item["trade_date"], item["old"], item["new"]) for item in diff} == {
        ("2026-01-02", True, False),
        ("2026-01-03", False, None),
        ("2026-01-04", None, True),
    }


def test_diff_超过上限_截断且统计完整():
    new_rows = {
        date(2000, 1, 1) + timedelta(days=i): True
        for i in range(tcc.DIFF_LIMIT + 1)
    }

    stats, diff, truncated = _diff_rows({}, new_rows)

    assert truncated is True
    assert len(diff) == tcc.DIFF_LIMIT
    assert stats["inserted"] == tcc.DIFF_LIMIT + 1


# ==================== 测试专用注入 ====================


def test_install_snapshot_无日期且无覆盖区间_抛ValueError():
    cache = TradingCalendarCache(client=_FakeClient(), router=_FakeRouter())

    with pytest.raises(ValueError):
        cache.install_snapshot([])


# ==================== 状态报告 ====================


def test_describe_合并内存快照与DB状态():
    client = _FakeClient(
        state_rows=[{
            "id": True,
            "coverage_start": "2020-01-01",
            "coverage_end": "2026-12-31",
            "last_success_at": "2026-10-01T00:00:00+08:00",
            "last_error": None,
            "last_error_at": None,
        }],
        trading_rows=[
            {"trade_date": date(2026, 1, 1), "is_trading_day": False},
            {"trade_date": date(2026, 1, 5), "is_trading_day": True},
            {"trade_date": date(2026, 1, 6), "is_trading_day": True},
        ],
    )
    cache = TradingCalendarCache(client=client, router=_FakeRouter())
    cache.install_snapshot(
        [date(2026, 1, 5)], coverage_start=date(2026, 1, 1), coverage_end=date(2026, 12, 31)
    )

    report = cache.describe()

    assert report["ready"] is True
    assert report["coverage_start"] == "2020-01-01"  # 以 DB state 为准
    assert report["last_success_at"] == "2026-10-01T00:00:00+08:00"
    assert report["days"] == 3
    assert report["trading_days"] == 2
    assert report["snapshot"]["trading_days"] == 1


def test_describe_DB异常_带db_error不抛():
    cache = TradingCalendarCache(client=_FakeClient(fail=True), router=_FakeRouter())
    cache.install_snapshot([date(2026, 1, 5)])

    report = cache.describe()

    assert report["ready"] is True
    assert "DB 连接失败" in report["db_error"]
