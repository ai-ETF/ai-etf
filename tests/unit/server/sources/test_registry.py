"""源注册表与进程内默认路由器单元测试。

模块名称：server/sources/registry.py、server/sources/__init__.py
所测功能：源注册/去重、操作 → 能力集合的映射、默认源清单、
         `get_router()` 的进程内单例语义。
测试方法：用只含 `SourceMeta` 的假源构造注册表；不联网、不连数据库。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.1 / §4.3 / §9.1。
"""
import pytest

from server.sources import get_router, reset_router
from server.sources.models import SourceMeta
from server.sources.registry import Registry, default_sources


class _FakeSource:
    def __init__(self, name, capabilities, domain="d.example.com", priority=100):
        self.meta = SourceMeta(
            name=name,
            domain=domain,
            capabilities=frozenset(capabilities),
            priority=priority,
        )


@pytest.fixture
def registry():
    return Registry.with_sources(
        [
            _FakeSource("h", {"history"}),
            _FakeSource("r", {"history_recent"}),
            _FakeSource("l", {"latest"}),
            _FakeSource("b", {"batch"}),
            _FakeSource("c", {"calendar"}),
        ]
    )


# ==================== 正常数据：能力检索 ====================


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("history", ["h"]),
        ("history_recent", ["h", "r"]),
        ("latest", ["h", "r", "l"]),
        ("batch", ["b"]),
        ("calendar", ["c"]),
    ],
)
def test_按操作检索候选能力(registry, operation, expected):
    """`latest` 可以退而使用 history / history_recent 源（能力分层）。"""
    assert [s.meta.name for s in registry.by_capability(operation)] == expected


def test_注册后可取值且列出全部(registry):
    assert registry.get("h").meta.name == "h"
    assert registry.get("missing") is None
    assert [s.meta.name for s in registry.all()] == ["h", "r", "l", "b", "c"]


# ==================== 异常 / 边界 ====================


def test_重复源名注册直接失败():
    registry = Registry()
    registry.register(_FakeSource("dup", {"history"}))

    with pytest.raises(ValueError, match="重复注册"):
        registry.register(_FakeSource("dup", {"calendar"}))


def test_未知操作显式报错():
    registry = Registry()

    with pytest.raises(ValueError, match="未知能力"):
        registry.by_capability("fund_catalog")


def test_空注册表检索返回空列表(registry):
    empty = Registry()

    assert empty.by_capability("history") == []
    assert empty.all() == []


# ==================== 默认源清单 ====================


def test_默认源清单覆盖净值与日历五源():
    """`sina_index_daily` 按 §6.2 决策不注册：它给不出未来交易日。"""
    sources = default_sources()

    assert [s.meta.name for s in sources] == [
        "em_pingzhongdata",
        "em_fund_jjjz",
        "em_lsjz",
        "em_mobile",
        "sina_trade_date",
    ]
    assert len({s.meta.name for s in sources}) == 5
    assert "sina_index_daily" not in {s.meta.name for s in sources}


def test_默认源域名符合设计文档():
    domains = {s.meta.name: s.meta.domain for s in default_sources()}

    assert domains["em_pingzhongdata"] == "fund.eastmoney.com"
    assert domains["em_fund_jjjz"] == "fund.eastmoney.com"
    assert domains["em_lsjz"] == "api.fund.eastmoney.com"
    assert domains["em_mobile"] == "fundmobapi.eastmoney.com"
    assert domains["sina_trade_date"] == "finance.sina.com.cn"
    assert "sina_index_daily" not in domains


def test_get_router返回进程内单例():
    reset_router()
    try:
        first = get_router()

        assert get_router() is first

        reset_router()
        assert get_router() is not first
    finally:
        reset_router()
