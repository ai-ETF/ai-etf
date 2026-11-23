"""fund_nav_service 单元测试：净值读入口的目录边界、批量读取与「指定日期」五步判定。

模块名称：server/services/fund_nav_service.py
所测功能：`get_latest`、`get_latest_batch`、`in_catalog`、`get_history`（含分页与读穿透）、
         `get_nav_on`（四态判定，顺序不可调换）
测试方法：内存 FakeClient 记录查询链并按 `range` 切片、FakeSync 替身；不连 Supabase、不触网。

判定的业务前提（存储设计 §2.5）：净值每天只公布一次，订单按 `confirm_date` 当日净值确认。
因此「今天没有」和「这一天本来就没有」必须区分开 —— 前者要等，后者重试无用。
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from server.services.fund_nav_service import (
    FundNavService,
    FundNavUnavailable,
    NavLookupStatus,
    _PAGE_SIZE,
)
from server.services.fund_nav_sync_service import HistoryFillResult
from server.sources.models import NavPoint


class _FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _FakeTable:
    """只做「按表名取行 + range/limit 切片」，不解析 eq/in 过滤。

    每个用例只针对一个基金代码，因此忽略过滤条件不影响结论；需要区分多行时
    由用例直接配置该表的返回值。
    """

    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._limit = None
        self._range = None

    def select(self, fields=None, count=None):
        return self

    def eq(self, column, value):
        return self

    def in_(self, column, values):
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self.store["ranges"].append((self.name, start, end))
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self.store["rows"].get(self.name, []))
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        elif self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResult(rows, count=len(self.store["rows"].get(self.name, [])))


class _FakeClient:
    def __init__(self, rows=None):
        self.store = {"rows": rows or {}, "ranges": []}

    def table(self, name):
        return _FakeTable(self.store, name)


class _FakeSync:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def ensure_history(self, code):
        self.calls.append(code)
        return self.result or HistoryFillResult(fund_code=code, status="ready")


def _nav_row(code="110020", nav_date="2026-10-23", unit="1.7626"):
    return {
        "fund_code": code,
        "nav_date": nav_date,
        "unit_nav": Decimal(unit),
        "accumulated_nav": Decimal(unit),
        "daily_growth": Decimal("0.12"),
        "source": "em_pingzhongdata",
    }


def _state(**overrides):
    row = {
        "fund_code": "110020",
        "history_status": "ready",
        "latest_nav_date": "2026-10-23",
        "latest_unit_nav": Decimal("1.7626"),
        "history_start_date": "2011-05-06",
        "last_checked_at": "2026-10-23T20:06:00+08:00",
        "last_error": None,
    }
    row.update(overrides)
    return row


# ==================== 最新净值 ====================


def test_没有状态行时get_latest返回None而不是报错():
    nav = FundNavService(client=_FakeClient())
    assert nav.get_latest("110020") is None


def test_get_latest读state投影不做全表扫描():
    client = _FakeClient({"fund_nav_state": [_state()]})
    latest = FundNavService(client=client).get_latest("110020")

    assert latest.unit_nav == Decimal("1.7626")
    assert latest.nav_date == date(2026, 10, 23)
    assert client.store["ranges"] == []  # 单只读取不走分页


def test_批量读取跳过没有净值与净值缺失的行():
    client = _FakeClient({"fund_nav_state": [
        _state(),
        _state(fund_code="000008", latest_nav_date=None),
        _state(fund_code="161725", latest_unit_nav=None),
    ]})

    result = FundNavService(client=client).get_latest_batch(
        ["110020", "000008", "161725"]
    )

    assert list(result) == ["110020"]


def test_批量读取空列表直接返回不发查询():
    client = _FakeClient()
    assert FundNavService(client=client).get_latest_batch([]) == {}
    assert client.store["ranges"] == []


# ==================== 目录边界 ====================


def test_in_catalog空代码不查库直接False():
    """空代码不能变成一次全表 `ILIKE` 之类的查询。"""
    client = _FakeClient({"fund_catalog": [{"fund_code": "110020"}]})
    assert FundNavService(client=client).in_catalog("   ") is False


def test_in_catalog按目录视图命中判定():
    client = _FakeClient({"fund_catalog": [{"fund_code": "110020"}]})
    assert FundNavService(client=client).in_catalog("110020") is True

    empty = _FakeClient({"fund_catalog": []})
    assert FundNavService(client=empty).in_catalog("512890") is False


# ==================== 指定日期五步判定 ====================

@pytest.mark.parametrize(
    "情况, 行, 状态, 原因",
    [
        ("命中", {"fund_nav": [_nav_row()]}, NavLookupStatus.OK, None),
        ("连状态行都没有", {}, NavLookupStatus.FETCH_FAILED, "no_state"),
        (
            "状态行没有最新净值",
            {"fund_nav_state": [_state(latest_nav_date=None)]},
            NavLookupStatus.FETCH_FAILED,
            "history_not_complete",
        ),
        (
            "查询日晚于最新净值日",
            {"fund_nav_state": [_state(latest_nav_date="2026-10-22")]},
            NavLookupStatus.NOT_YET_PUBLISHED,
            None,
        ),
        (
            "历史未补齐却声称覆盖",
            {"fund_nav_state": [_state(history_status="partial")]},
            NavLookupStatus.FETCH_FAILED,
            "history_not_complete",
        ),
        (
            "起点未知无法判断缺口",
            {"fund_nav_state": [_state(history_start_date=None)]},
            NavLookupStatus.FETCH_FAILED,
            "history_start_unknown",
        ),
        (
            "覆盖区间内的真实缺口",
            {"fund_nav_state": [_state()]},
            NavLookupStatus.FETCH_FAILED,
            "gap",
        ),
    ],
)
def test_get_nav_on判定顺序(情况, 行, 状态, 原因):
    """五步顺序不可调换：先看有没有值，再看「是不是还没公布」，最后才判缺口/无净值日。"""
    lookup = FundNavService(client=_FakeClient(行)).get_nav_on(
        "110020", date(2026, 10, 23)
    )

    assert lookup.status is 状态, 情况
    assert lookup.reason == 原因


def test_早于成立日判为无净值日而非缺口():
    """NO_NAV 的补充排查提示：早于成立日 vs 早于历史起点（不改变状态本身）。"""
    client = _FakeClient({
        "fund_nav_state": [_state(history_start_date="2020-01-02")],
        "fund": [{"establish_date": "2015-03-01"}],
    })

    lookup = FundNavService(client=client).get_nav_on("110020", date(2014, 1, 2))

    assert lookup.status is NavLookupStatus.NO_NAV
    assert lookup.reason == "before_establishment"


def test_查询日不是date类型直接TypeError():
    """日期类型错是调用方 bug，不能静默当成字符串处理。"""
    with pytest.raises(TypeError):
        FundNavService(client=_FakeClient()).get_nav_on("110020", "2026-10-23")


# ==================== 历史净值 ====================


def test_全量历史按1000行分页读取且返回升序():
    """PostgREST 单次最多 1000 行；只读一页会静默截断全量历史（约 4000 点）。"""
    total = _PAGE_SIZE + 3
    desc_rows = [
        _nav_row(nav_date=(date(2000, 1, 1) + timedelta(days=i)).isoformat())
        for i in reversed(range(total))
    ]
    client = _FakeClient({
        "fund_nav_state": [_state()],
        "fund_nav": desc_rows,
    })

    points = FundNavService(client=client).get_history("110020")

    assert len(points) == _PAGE_SIZE + 3
    assert [r[1] for r in client.store["ranges"]] == [0, _PAGE_SIZE]
    assert points[0].nav_date <= points[-1].nav_date


def test_历史未补齐时先读穿透补齐再返回():
    sync = _FakeSync(HistoryFillResult(fund_code="110020", status="ready"))
    client = _FakeClient({
        "fund_nav_state": [_state(history_status="pending")],
        "fund_nav": [_nav_row()],
    })

    points = FundNavService(client=client, sync=sync).get_history("110020", limit=2)

    assert sync.calls == ["110020"]
    assert len(points) == 1


def test_补数失败抛Unavailable而不是返回片段():
    """「上游失败」不能伪装成「该基金没有历史」，API 层据此返回 503。"""
    sync = _FakeSync(
        HistoryFillResult(fund_code="110020", status="failed", error="所有源都失败")
    )
    client = _FakeClient({
        "fund_nav_state": [_state(history_status="partial")],
        "fund_nav": [_nav_row()],
    })

    with pytest.raises(FundNavUnavailable) as excinfo:
        FundNavService(client=client, sync=sync).get_history("110020")

    assert excinfo.value.reason == "failed"
    assert excinfo.value.detail == "所有源都失败"


def test_已经ready的历史不触网():
    sync = _FakeSync()
    client = _FakeClient({"fund_nav_state": [_state()], "fund_nav": [_nav_row()]})

    FundNavService(client=client, sync=sync).get_history("110020")

    assert sync.calls == []


def test_limit非正数抛ValueError():
    with pytest.raises(ValueError):
        FundNavService(client=_FakeClient()).get_history("110020", limit=0)


def test_NavPoint字段映射完整():
    """写库行 → 领域模型的映射：`source` 缺失时给空串而不是 None（NavPoint 契约是 str）。"""
    client = _FakeClient({
        "fund_nav_state": [_state()],
        "fund_nav": [{**_nav_row(), "source": None}],
    })

    point = FundNavService(client=client).get_history("110020")[0]

    assert isinstance(point, NavPoint)
    assert point.source == ""
    assert point.unit_nav == Decimal("1.7626")
