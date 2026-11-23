"""东财 pingzhongdata 净值源单元测试。

模块名称：server/sources/em_pingzhongdata.py
所测功能：JS 数组解析、单位净值与累计净值按日期合并、limit 截取、
         货基拒绝、格式漂移/空数据/非法 JSON 的失败分类、URL 构造。
测试方法：内联两组合法上游 JS 样本 + 异常样本，纯函数直测；
         源类用子类覆盖 `_get_text` 注入样本；不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §6.1 字段映射与坑 1/坑 2。
"""
from datetime import date
from decimal import Decimal

import pytest

from server.sources.em_pingzhongdata import (
    EmPingzhongdataSource,
    parse_pingzhongdata,
)
from server.sources.models import FailureKind, SourceError

# 正常样本：累计净值数组刻意倒序，验证「按日期合并」而不是按下标对齐
PINGZHONGDATA_NORMAL = (
    'var fS_name = "测试联接A";'
    'var Data_netWorthTrend = ['
    '{"x":1791993600000,"y":1.7196,"equityReturn":-1.17,"unitMoney":""},'
    '{"x":1792080000000,"y":1.7219,"equityReturn":0.13,"unitMoney":""}'
    '];'
    'var Data_ACWorthTrend = [[1792080000000,1.8219],[1791993600000,1.8196]];'
)

# 缺失累计净值、尾逗号、缺 equityReturn：验证可选字段与 JS 尾逗号兼容
PINGZHONGDATA_MINIMAL = (
    'var fS_name = "另一只债券基金";'
    'var Data_netWorthTrend = ['
    '{"x":1791993600000,"y":"1.0200"},'
    '{"x":1792080000000,"y":1.0235,"equityReturn":0.34},'
    '];'
)


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== 正常数据：两种上游形态 ====================


def test_单位净值与累计净值按日期合并():
    points = parse_pingzhongdata(PINGZHONGDATA_NORMAL, "110020", "s")

    assert [p.nav_date for p in points] == [date(2026, 10, 15), date(2026, 10, 16)]
    assert points[0].unit_nav == Decimal("1.7196")
    assert points[0].accumulated_nav == Decimal("1.8196")
    assert points[0].daily_growth == Decimal("-1.17")
    assert points[1].unit_nav == Decimal("1.7219")
    assert points[1].accumulated_nav == Decimal("1.8219")
    assert points[1].daily_growth == Decimal("0.13")


def test_缺失累计净值与日增长率时字段为空但净值仍可用():
    points = parse_pingzhongdata(PINGZHONGDATA_MINIMAL, "110020", "s")

    assert len(points) == 2
    assert points[0].unit_nav == Decimal("1.0200")
    assert points[0].accumulated_nav is None
    assert points[0].daily_growth is None
    assert points[1].daily_growth == Decimal("0.34")


def test_limit只取最近N条():
    points = parse_pingzhongdata(PINGZHONGDATA_NORMAL, "110020", "s", limit=1)

    assert len(points) == 1
    assert points[0].nav_date == date(2026, 10, 16)


# ==================== 异常 / 边界 ====================


@pytest.mark.parametrize("limit", [0, -1])
def test_limit非法直接拒绝(limit):
    with pytest.raises(SourceError) as excinfo:
        parse_pingzhongdata(PINGZHONGDATA_NORMAL, "110020", "s", limit=limit)

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


def test_货币基金拒绝而不是当净值():
    text = 'var fS_name = "天弘余额宝货币";var something=1;'

    with pytest.raises(SourceError) as excinfo:
        parse_pingzhongdata(text, "000198", "s")

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST
    assert "货币" in excinfo.value.message


def test_格式漂移记SCHEMA_DRIFT():
    with pytest.raises(SourceError) as excinfo:
        parse_pingzhongdata('var fS_name = "测试基金";', "110020", "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_空净值数组记EMPTY_PAYLOAD():
    text = 'var fS_name = "测试基金";var Data_netWorthTrend = [];'

    with pytest.raises(SourceError) as excinfo:
        parse_pingzhongdata(text, "110020", "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_非法JS数组记PARSE_ERROR():
    text = 'var fS_name = "测试基金";var Data_netWorthTrend = [{"x": oops}];'

    with pytest.raises(SourceError) as excinfo:
        parse_pingzhongdata(text, "110020", "s")

    assert _kind(excinfo) == FailureKind.PARSE_ERROR


# ==================== 源类：URL 与 limit 透传 ====================


class StubPingzhongdataSource(EmPingzhongdataSource):
    def __init__(self, text=PINGZHONGDATA_NORMAL):
        super().__init__()
        self.text = text
        self.urls: list = []

    def _get_text(self, url, **kwargs):
        self.urls.append(url)
        return self.text


def test_源类按基金代码构造URL并透传limit():
    source = StubPingzhongdataSource()

    points = source.fetch_history("110020", limit=1)

    assert source.urls == ["https://fund.eastmoney.com/pingzhongdata/110020.js"]
    assert len(points) == 1
