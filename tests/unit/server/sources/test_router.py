"""源路由器单元测试。

模块名称：server/sources/router.py
所测功能：按能力选源、偏好排序、denylist、逐源尝试、静默空转失败、
         `AllSourcesFailed` 上下文、非 `SourceError` 的接口级降级、
         日期归一化/去重/取最近 N 条、批量零命中告警、不回切。
测试方法：`ScriptedSource` 按脚本返回固定值或抛固定异常；健康状态注入假时钟的
         `HealthTracker`；`caplog` 解析结构化事件；不联网、不连数据库。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.2 / §5.1 / §5.2 / §5.4 / §7 / §8.1。
"""
import json
import logging
from datetime import date
from decimal import Decimal

import pytest

from server.sources.config import AdapterConfig
from server.sources.health import HealthTracker
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


def _router(sources, health=None, **config_kwargs):
    config = AdapterConfig(**config_kwargs)
    return SourceRouter(
        registry=Registry.with_sources(sources),
        health=health,
        config=config,
    )


# ==================== 逐源尝试 ====================


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


def test_全部源都在冷却时仍抛AllSourcesFailed():
    a = ScriptedSource(
        "a", "domain-a", history=SourceError("a", FailureKind.TIMEOUT, "timeout")
    )
    router = _router([a])

    for _ in range(3):
        with pytest.raises(AllSourcesFailed):
            router.fetch_history("110020")

    with pytest.raises(AllSourcesFailed) as excinfo:
        router.fetch_history("110020")

    assert excinfo.value.tried == []
    assert "没有可用的候选源" in str(excinfo.value)


def test_源抛非SourceError记接口级失败并继续换源(caplog):
    """源契约只允许抛 `SourceError`；未包装的异常按 `UNEXPECTED` 接口级处理。

    只软降级该源、继续换源，同时以 ERROR + 堆栈记录，避免代码缺陷被当成
    普通上游失败而悄悄消失。
    """
    a = ScriptedSource(
        "a", "domain-a", priority=10, history=ValueError("解析代码 bug")
    )
    b = ScriptedSource("b", "domain-b", history=[_point("110020", 2)])
    health = HealthTracker(config=AdapterConfig())
    router = _router([a, b], health=health)

    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        result = router.fetch_history("110020")

    # 换源成功，原异常没有向上暴露
    assert [p.nav_date for p in result] == [date(2026, 1, 2)]
    assert len(a.history_calls) == 1
    assert len(b.history_calls) == 1

    # 接口级失败：域名不动，只降级源 a
    assert health.domain_snapshot("domain-a").consecutive_failures == 0
    assert health.domain_snapshot("domain-a").state == "closed"
    source_health = health.source_snapshot("a")
    assert source_health.last_failure_kind == "UNEXPECTED"
    assert source_health.degraded_until > 0

    # 日志：ERROR 级别且带原始堆栈
    failures = [
        record
        for record in caplog.records
        if json.loads(record.message).get("kind") == "UNEXPECTED"
    ]
    assert failures
    payload = json.loads(failures[0].message)
    assert failures[0].levelno == logging.ERROR
    assert failures[0].exc_info is not None
    assert payload["source"] == "a"
    assert payload["ok"] is False
    assert "ValueError: 解析代码 bug" in payload["error"]


def test_全部源抛非SourceError时抛AllSourcesFailed并保留原始错误():
    a = ScriptedSource("a", "domain-a", priority=10, history=KeyError("DWJZ"))
    b = ScriptedSource("b", "domain-b", history=TypeError("rows 不是 list"))

    with pytest.raises(AllSourcesFailed) as excinfo:
        _router([a, b]).fetch_history("110020")

    error = excinfo.value
    assert [item["source"] for item in error.tried] == ["a", "b"]
    assert [item["kind"] for item in error.tried] == ["UNEXPECTED", "UNEXPECTED"]
    assert "KeyError" in error.tried[0]["error"]
    assert "TypeError" in error.tried[1]["error"]


# ==================== 选源：偏好 / denylist / 能力分层 ====================


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
    assert len(a.history_calls) == 1
    assert len(b.history_calls) == 2


# ==================== 归一化：日期、去重、limit ====================


def test_历史净值按日期升序并保留同日最后一条():
    points = [
        _point("110020", 2, "1.20"),
        _point("110020", 1, "1.10"),
        _point("110020", 2, "1.25"),
    ]
    source = ScriptedSource("a", "domain-a", history=points, respect_limit=False)

    result = _router([source]).fetch_history("110020")

    assert [p.nav_date for p in result] == [date(2026, 1, 1), date(2026, 1, 2)]
    assert result[-1].unit_nav == Decimal("1.25")


def test_最近N条只返回尾部且保持升序():
    points = [_point("110020", day, f"1.{day}0") for day in (1, 2, 3)]
    source = ScriptedSource("a", "domain-a", history=points, respect_limit=False)

    result = _router([source]).fetch_history_recent("110020", 2)

    assert [p.nav_date for p in result] == [date(2026, 1, 2), date(2026, 1, 3)]
    assert source.history_calls == [("110020", 2)]


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


# ==================== 批量 ====================


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


def test_批量源返回空字典仍视为成功():
    """批量源「没有覆盖请求的代码」不是失败：不抛 AllSourcesFailed，返回空映射。"""
    a = ScriptedSource("a", "domain-a", capabilities=("batch",), batch={})

    result = _router([a]).fetch_latest_batch(["110020"])

    assert result == {}
    assert a.batch_calls == [["110020"]]


def test_批量过滤后零命中记WARNING(caplog):
    """请求非空却零命中：保持成功语义，但必须留一条可观测告警。"""
    a = ScriptedSource(
        "a",
        "domain-a",
        capabilities=("batch",),
        batch={"999999": [_point("999999", 2)]},
    )

    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        result = _router([a]).fetch_latest_batch(["110020"])

    assert result == {}
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "batch_empty"
    assert payload["capability"] == "batch"
    assert payload["source"] == "a"
    assert payload["domain"] == "domain-a"
    assert payload["requested"] == 1
    assert payload["returned"] == 1
    assert payload["sample"] == ["110020"]
    assert caplog.records[-1].levelno == logging.WARNING


# ==================== 日历 ====================


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


# ==================== 入口快速失败 ====================


@pytest.mark.parametrize("code", ["", "   "])
def test_空基金代码快速失败(code):
    a = ScriptedSource("a", "domain-a", history=[_point("110020", 1)])

    with pytest.raises(ValueError, match="基金代码"):
        _router([a]).fetch_history(code)

    assert a.history_calls == []


@pytest.mark.parametrize("limit", [0, -5])
def test_最近N条limit非法快速失败(limit):
    a = ScriptedSource("a", "domain-a", history=[_point("110020", 1)])

    with pytest.raises(ValueError, match="limit"):
        _router([a]).fetch_history_recent("110020", limit)

    assert a.history_calls == []


def test_批量请求空代码快速失败():
    a = ScriptedSource("a", "domain-a", capabilities=("batch",), batch={})

    with pytest.raises(ValueError, match="codes"):
        _router([a]).fetch_latest_batch(["  ", ""])

    assert a.batch_calls == []
