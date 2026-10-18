"""真实上游契约测试：验证每个源仍然能解析今天的返回。

运行方式（**默认不跑**，需真实出网）：

    poetry run pytest tests/integration/server/sources -m integration_net

设计文档 §8.2 的要求：

- 断言真实返回能被解析成 `NavPoint`（不是「应该能」）；
- 断言**行数量级**（批量源 2 万行量级、单只源千行量级），防「静默返回 1 行」；
- 断言字段结构（如 `em_fund_jjjz` 的日期来自 `showday`）而不是具体某一天；
- akshare 升级前必须全绿。
"""
from decimal import Decimal

import pytest

from server.sources.models import FailureKind, SourceError
from server.sources.router import SourceRouter

pytestmark = [pytest.mark.integration, pytest.mark.integration_net]

CODE = "110020"          # 普通场外联接基金
MONEY_FUND = "000198"    # 货币基金（用于验证拒绝逻辑）


@pytest.fixture(scope="module")
def router():
    return SourceRouter()


# ==================== 净值线四源 ====================


def test_em_pingzhongdata_返回全量历史且字段可解析():
    from server.sources.em_pingzhongdata import EmPingzhongdataSource

    points = EmPingzhongdataSource().fetch_history(CODE)

    # 110020 实测 4163 点；低于 1000 说明响应被截断或格式变了
    assert len(points) > 1000, f"{CODE} 只解析出 {len(points)} 个净值点"
    assert all(p.fund_code == CODE for p in points)
    assert all(p.nav_date for p in points)
    assert all(p.unit_nav is not None for p in points)
    # 累计净值应不早于单位净值出现，且数值关系合理
    assert any(p.accumulated_nav is not None for p in points)
    assert points[-1].nav_date >= points[0].nav_date


def test_em_pingzhongdata_limit只取最近N条():
    from server.sources.em_pingzhongdata import EmPingzhongdataSource

    points = EmPingzhongdataSource().fetch_history(CODE, limit=5)

    assert len(points) == 5
    assert points == sorted(points, key=lambda p: p.nav_date)


def test_em_fund_jjjz_批量窗口内每个代码都有点():
    """批量源内部强制 >=1000 行，能成功返回即说明行数量级正常。"""
    from server.sources.em_fund_jjjz import EmFundJjjzSource

    result = EmFundJjjzSource().fetch_latest_batch([CODE, "000001"])

    assert CODE in result
    assert 1 <= len(result[CODE]) <= 2
    for points in result.values():
        assert all(p.unit_nav is not None or p.accumulated_nav is not None for p in points)
        assert len({p.nav_date for p in points}) == len(points)


def test_em_lsjz_最近净值可解析():
    from server.sources.em_lsjz import EmLsjzSource

    points = EmLsjzSource().fetch_history(CODE, limit=20)

    assert len(points) == 20, "pageSize=20 是服务端上限，应当拿满 20 条"
    assert all(p.unit_nav is not None for p in points)
    assert points == sorted(points, key=lambda p: p.nav_date)


def test_em_mobile_最新净值可解析():
    from server.sources.em_mobile import EmMobileSource

    points = EmMobileSource().fetch_history(CODE, limit=1)

    assert len(points) == 1
    point = points[0]
    assert point.fund_code == CODE
    assert point.unit_nav is not None
    assert point.unit_nav > Decimal("0")


# ==================== 货基必须被拒绝（坑 2） ====================


@pytest.mark.parametrize("source_name", ["em_lsjz", "em_mobile", "em_pingzhongdata"])
def test_货基不会被当成净值(source_name):
    """货基 DWJZ=万份收益、LJJZ=7日年化，绝不能写进 unit_nav。"""
    import importlib

    module = importlib.import_module(f"server.sources.{source_name}")
    class_name = {
        "em_lsjz": "EmLsjzSource",
        "em_mobile": "EmMobileSource",
        "em_pingzhongdata": "EmPingzhongdataSource",
    }[source_name]
    source = getattr(module, class_name)()

    with pytest.raises(SourceError) as excinfo:
        source.fetch_history(MONEY_FUND, limit=5 if source_name != "em_pingzhongdata" else None)

    assert excinfo.value.kind == FailureKind.INVALID_REQUEST


# ==================== 交易日历两源 ====================


def test_sina_trade_date_全量日历可解析():
    from server.sources.sina_trade_date import SinaTradeDateSource

    data = SinaTradeDateSource().fetch_calendar()

    assert len(data.trading_days) > 1000
    assert data.coverage_start < data.coverage_end
    assert data.source == "sina_trade_date"


def test_sina_index_daily_可反推交易日():
    from server.sources.sina_index_daily import SinaIndexDailySource

    data = SinaIndexDailySource().fetch_calendar()

    assert len(data.trading_days) > 1000
    assert data.coverage_start < data.coverage_end


# ==================== 路由器端到端 ====================


def test_router_净值与日历端到端可用(router):
    history = router.fetch_history(CODE)
    assert len(history) > 1000

    latest = router.fetch_latest(CODE)
    assert latest.fund_code == CODE
    assert latest.unit_nav is not None

    calendar = router.fetch_calendar()
    assert len(calendar.trading_days) > 1000
