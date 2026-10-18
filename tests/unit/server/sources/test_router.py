"""路由器单测：逐个尝试、偏好排序、denylist、AllSourcesFailed、不回切。"""
from datetime import date
from decimal import Decimal

import pytest

from server.sources.config import AdapterConfig
from server.sources.models import (
    AllSourcesFailed,
    CalendarData,
    FailureKind,
    NavPoint,
    SourceError,
    SourceMeta,
)
from server.sources.registry import Registry
from server.sources.router import SourceRouter


def _point(code: str, day: int, nav: str = "1.0") -> NavPoint:
    return NavPoint(
        fund_code=code,
        nav_date=date(2026, 1, day),
        unit_nav=Decimal(nav),
        accumulated_nav=Decimal(nav),
        daily_growth=None,
        source="fake",
    )


class ScriptedSource:
    """按脚本返回固定值或抛固定 ``SourceError`` 的假源。"""

    def __init__(
        self,
        name: str,
        domain: str,
        *,
        history=None,
        batch=None,
        calendar=None,
        capabilities=("history",),
        priority: int = 100,
        respect_limit: bool = True,
    ):
        self.meta = SourceMeta(
            name=name,
            domain=domain,
            capabilities=frozenset(capabilities),
            priority=priority,
        )
        self._history = history
        self._batch = batch
        self._calendar = calendar
        self._respect_limit = respect_limit
        self.history_calls: list = []
        self.batch_calls: list = []
        self.calendar_calls = 0

    def fetch_history(self, code, limit=None):
        self.history_calls.append((code, limit))
        value = self._history
        if isinstance(value, Exception):
            raise value
        points = list(value or [])
        if limit is not None and self._respect_limit:
            return points[-limit:]
        return points

    def fetch_latest_batch(self, codes):
        self.batch_calls.append(list(codes))
        value = self._batch
        if isinstance(value, Exception):
            raise value
        return value or {}

    def fetch_calendar(self):
        self.calendar_calls += 1
        value = self._calendar
        if isinstance(value, Exception):
            raise value
        return value


def _router(sources, **config_kwargs):
    config = AdapterConfig(**config_kwargs)
    return SourceRouter(registry=Registry.with_sources(sources), config=config)


def test_首选失败自动切到次选():
    a = ScriptedSource(
        "a", "domain-a", priority=10,
        history=SourceError("a", FailureKind.TIMEOUT, "timeout"),
    )
    b = ScriptedSource("b", "domain-b", priority=100, history=[_point("110020", 2)])

    result = _router([a, b]).fetch_history("110020")

    assert [p.nav_date for p in result] == [date(2026, 1, 2)]
    assert len(a.history_calls) == 1
    assert len(b.history_calls) == 1


def test_源静默返回空也算失败并继续切源():
    a = ScriptedSource("a", "domain-a", priority=10, history=[])
    b = ScriptedSource("b", "domain-b", priority=100, history=[_point("110020", 2)])

    result = _router([a, b]).fetch_history("110020")

    assert len(result) == 1
    assert len(b.history_calls) == 1


def test_全部失败抛AllSourcesFailed且带上试过的源():
    a = ScriptedSource(
        "a", "domain-a", priority=10,
        history=SourceError("a", FailureKind.TIMEOUT, "timeout"),
    )
    b = ScriptedSource(
        "b", "domain-b", priority=100,
        history=SourceError("b", FailureKind.EMPTY_PAYLOAD, "empty"),
    )

    with pytest.raises(AllSourcesFailed) as excinfo:
        _router([a, b]).fetch_history("110020")

    error = excinfo.value
    assert error.capability == "history"
    assert [item["source"] for item in error.tried] == ["a", "b"]
    assert [item["kind"] for item in error.tried] == ["TIMEOUT", "EMPTY_PAYLOAD"]


def test_偏好环境变量覆盖默认顺序():
    a = ScriptedSource("a", "domain-a", priority=10, history=[])
    b = ScriptedSource("b", "domain-b", priority=100, history=[])

    router = _router([a, b], priority_overrides={"b": 0, "a": 1})
    assert [s.meta.name for s in router.pick("history")] == ["b", "a"]


def test_denylist按域名整体停用():
    a = ScriptedSource("a", "domain-a", priority=10, history=[])
    b = ScriptedSource("b", "domain-b", priority=100, history=[])

    router = _router([a, b], denylist=frozenset({"domain-a"}))
    assert [s.meta.name for s in router.pick("history")] == ["b"]


def test_能力分层_latest可退而使用history源():
    history_only = ScriptedSource(
        "h", "domain-h", capabilities=("history",), priority=100, history=[]
    )
    latest_only = ScriptedSource(
        "l", "domain-l", capabilities=("latest",), priority=90, history=[]
    )
    batch_only = ScriptedSource(
        "b", "domain-b", capabilities=("batch",), priority=1, batch={}
    )

    router = _router([history_only, latest_only, batch_only])
    assert [s.meta.name for s in router.pick("latest")] == ["l", "h"]


def test_fetch_latest按日期取最大而不是相信源的顺序():
    out_of_order = [_point("110020", 3, "1.3"), _point("110020", 1, "1.1")]
    a = ScriptedSource(
        "a",
        "domain-a",
        capabilities=("latest",),
        history=out_of_order,
        respect_limit=False,
    )

    point = _router([a]).fetch_latest("110020")

    assert point.nav_date == date(2026, 1, 3)
    assert point.unit_nav == Decimal("1.3")


def test_批量源返回全市场数据时按请求代码过滤():
    a = ScriptedSource(
        "a",
        "domain-a",
        capabilities=("batch",),
        batch={
            "110020": [_point("110020", 2)],
            "000001": [_point("000001", 2)],
            "999999": [_point("999999", 2)],
        },
    )

    result = _router([a]).fetch_latest_batch(["110020", "999999"])

    assert set(result) == {"110020", "999999"}
    assert a.batch_calls == [["110020", "999999"]]


def test_不回切_上次成功的源保持优先():
    """切到次选源后，即使首选源没被熔断，也不主动切回（设计文档 §5.4）。"""
    a = ScriptedSource(
        "a", "domain-a", priority=10,
        history=SourceError("a", FailureKind.TIMEOUT, "timeout"),
    )
    b = ScriptedSource("b", "domain-b", priority=100, history=[_point("110020", 2)])
    router = _router([a, b])

    router.fetch_history("110020")
    assert len(a.history_calls) == 1

    router.fetch_history("110020")
    # 第二次直接从 b 开始，a 不再被尝试
    assert len(a.history_calls) == 1
    assert len(b.history_calls) == 2


def test_日历源失败切换():
    a = ScriptedSource(
        "a", "domain-a", capabilities=("calendar",), priority=10,
        calendar=SourceError("a", FailureKind.PARSE_ERROR, "decode"),
    )
    b = ScriptedSource(
        "b", "domain-b", capabilities=("calendar",), priority=100,
        calendar=CalendarData(
            trading_days=frozenset({date(2026, 1, 5)}),
            coverage_start=date(2026, 1, 5),
            coverage_end=date(2026, 1, 5),
            source="b",
        ),
    )

    result = _router([a, b]).fetch_calendar()

    assert result.source == "b"
    assert a.calendar_calls == 1
