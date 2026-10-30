"""东财全市场批量净值源单元测试。

模块名称：server/sources/em_fund_jjjz.py
所测功能：`datas` 矩阵 + `showday` 日期对齐、T/T-1 两日净值映射、
         空净值行/短行过滤、行数量级保护、结构漂移分类、按请求代码过滤。
测试方法：用 `json.dumps` 构造两组上游矩阵样本（不同日期、不同字段完整度），
         纯函数直测；源类用子类覆盖 `_get_text`；不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §6.1 坑 1（日期来自 showday）。
"""
import json
from datetime import date
from decimal import Decimal

import pytest

from server.sources import em_fund_jjjz
from server.sources.em_fund_jjjz import EmFundJjjzSource, parse_batch_payload
from server.sources.models import FailureKind, SourceError


def _row(code, name="测试基金", unit="1.0000", acc="1.0000", prev_unit="", prev_acc="", growth=""):
    """21 列行样本；下标与上游一致：[0]代码、[3]/[4] T 日、[5]/[6] T-1、[8] 增长率。"""
    return [
        code, name, "CS", unit, acc, prev_unit, prev_acc, "0.0023", growth,
        "开放申购", "开放赎回", "", "1", "0", "1", "", "1",
        "0.10%", "0.10%", "1", "1.00%",
    ]


def _payload(rows, showday):
    return (
        'var db={chars:["0"],datas:'
        + json.dumps(rows)
        + ',count:["%d"],record:"%d",showday:' % (len(rows), len(rows))
        + json.dumps(list(showday))
        + "}"
    )


# 样本组一：普通股票型基金，T 日与 T-1 日字段齐全
PAYLOAD_FULL = _payload(
    [
        _row("110020", "测试联接A", "1.7219", "1.8219", "1.7196", "1.8196", "0.13"),
        _row("000001", "另一只基金"),
    ],
    ["2026-01-05", "2026-01-02"],
)

# 样本组二：T-1 日净值为空、另有短行；日期窗口不同，验证完全由 showday 驱动
PAYLOAD_PARTIAL = _payload(
    [
        _row("110020", "测试联接A", "2.0000", "2.5000", "", "", "0.10"),
        ["110020", "短行"],
    ],
    ["2026-01-07", "2026-01-06"],
)


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== 正常数据：两组窗口 ====================


def test_按showday解析T与T减一日(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)

    result = parse_batch_payload(PAYLOAD_FULL, {"110020", "000001"}, "s")

    points = result["110020"]
    assert [p.nav_date for p in points] == [date(2026, 1, 5), date(2026, 1, 2)]
    assert points[0].unit_nav == Decimal("1.7219")
    assert points[0].accumulated_nav == Decimal("1.8219")
    assert points[0].daily_growth == Decimal("0.13")
    assert points[1].unit_nav == Decimal("1.7196")
    assert points[1].daily_growth is None  # T-1 不臆造增长率
    assert result["000001"][0].unit_nav == Decimal("1.0000")


def test_T减一日为空时只返回当日点且短行被跳过(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)

    result = parse_batch_payload(PAYLOAD_PARTIAL, {"110020"}, "s")

    points = result["110020"]
    assert [p.nav_date for p in points] == [date(2026, 1, 7)]
    assert points[0].unit_nav == Decimal("2.0000")
    assert points[0].accumulated_nav == Decimal("2.5000")
    assert points[0].daily_growth == Decimal("0.10")


def test_未请求的代码不出现在结果里(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)

    result = parse_batch_payload(PAYLOAD_FULL, {"110020"}, "s")

    assert set(result) == {"110020"}


# ==================== 异常 / 边界 ====================


def test_行数明显少于正常量级记SCHEMA_DRIFT():
    with pytest.raises(SourceError) as excinfo:
        parse_batch_payload(PAYLOAD_FULL, {"110020"}, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT
    assert "疑似被截断" in excinfo.value.message


@pytest.mark.parametrize(
    "text",
    [
        'var db={chars:["0"],showday:["2026-01-05","2026-01-02"]}',
        'var db={chars:["0"],datas:[]}',
    ],
)
def test_缺少datas或showday记SCHEMA_DRIFT(text):
    with pytest.raises(SourceError) as excinfo:
        parse_batch_payload(text, {"110020"}, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_datas为空记EMPTY_PAYLOAD(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)
    text = _payload([], ["2026-01-05", "2026-01-02"])

    with pytest.raises(SourceError) as excinfo:
        parse_batch_payload(text, {"110020"}, "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_showday不足两天记SCHEMA_DRIFT(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)
    text = _payload([_row("110020")], ["2026-01-05"])

    with pytest.raises(SourceError) as excinfo:
        parse_batch_payload(text, {"110020"}, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_showday日期非法记SCHEMA_DRIFT(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)
    text = _payload([_row("110020")], ["2026-13-01", "2026-01-02"])

    with pytest.raises(SourceError) as excinfo:
        parse_batch_payload(text, {"110020"}, "s")

    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_空代码列表直接拒绝():
    with pytest.raises(SourceError) as excinfo:
        EmFundJjjzSource().fetch_latest_batch([" ", ""])

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


# ==================== 源类：请求参数 ====================


class StubFundJjjzSource(EmFundJjjzSource):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.calls: list = []

    def _get_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.text


def test_源类使用固定分页参数请求全市场(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)
    source = StubFundJjjzSource(PAYLOAD_FULL)

    result = source.fetch_latest_batch(["110020"])

    assert set(result) == {"110020"}
    url, kwargs = source.calls[0]
    assert url == "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    assert kwargs["params"]["page"] == "1,50000"
