"""东财移动端最新净值源单元测试。

模块名称：server/sources/em_mobile.py
所测功能：最新净值字段映射（`RZDF` 为日增长率）、可选字段缺失、
         货基拒绝、上游错误对象/空数据/非法日期分类、只提供最新一条的边界。
测试方法：内联两组上游 JSON 样本 + 子类覆盖 `_get_json`；不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §6.1 字段映射与 §11.3 第 4/5 条。
"""
from datetime import date
from decimal import Decimal

import pytest

from server.sources.em_mobile import EmMobileSource, parse_mobile_payload
from server.sources.models import FailureKind, SourceError

# 样本组一：普通指数型基金，字段齐全
MOBILE_NORMAL = {
    "Success": True,
    "ErrCode": 0,
    "Datas": {
        "FCODE": "110020",
        "FTYPE": "指数型-股票",
        "FSRQ": "2026-10-16",
        "DWJZ": "1.7219",
        "LJJZ": "1.8219",
        "RZDF": "0.13",
    },
}

# 样本组二：债券型基金，只保证日期与单位净值，其余字段缺失
MOBILE_MINIMAL = {
    "Success": True,
    "ErrCode": 0,
    "Datas": {"FTYPE": "债券型", "FSRQ": "2026-10-14", "DWJZ": "1.0200"},
}


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== 正常数据 ====================


def test_字段映射_日增长率用RZDF():
    point = parse_mobile_payload(MOBILE_NORMAL, "110020", "s")

    assert point.fund_code == "110020"
    assert point.nav_date == date(2026, 10, 16)
    assert point.unit_nav == Decimal("1.7219")
    assert point.accumulated_nav == Decimal("1.8219")
    assert point.daily_growth == Decimal("0.13")


def test_可选字段缺失时仍返回最新一条():
    point = parse_mobile_payload(MOBILE_MINIMAL, "110020", "s")

    assert point.nav_date == date(2026, 10, 14)
    assert point.unit_nav == Decimal("1.0200")
    assert point.accumulated_nav is None
    assert point.daily_growth is None


# ==================== 异常 / 边界 ====================


def test_货币基金拒绝():
    payload = {
        "Success": True,
        "ErrCode": 0,
        "Datas": {"FTYPE": "货币型", "FSRQ": "2026-10-17", "DWJZ": "0.2190"},
    }

    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload(payload, "000198", "s")

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


def test_Success为False记EMPTY_PAYLOAD():
    payload = {"Success": False, "ErrCode": 0, "Datas": MOBILE_NORMAL["Datas"]}

    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload(payload, "110020", "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_上游错误码记EMPTY_PAYLOAD():
    payload = {"Success": True, "ErrCode": "4", "ErrMsg": "not found", "Datas": {}}

    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload(payload, "110020", "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_Datas为空记EMPTY_PAYLOAD():
    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload({"Success": True, "ErrCode": 0, "Datas": {}}, "110020", "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_非法日期记EMPTY_PAYLOAD():
    payload = {
        "Success": True,
        "ErrCode": 0,
        "Datas": {"FTYPE": "股票型", "FSRQ": "bad", "DWJZ": "1.0"},
    }

    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload(payload, "110020", "s")

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_响应不是JSON对象记PARSE_ERROR():
    with pytest.raises(SourceError) as excinfo:
        parse_mobile_payload([], "110020", "s")

    assert _kind(excinfo) == FailureKind.PARSE_ERROR


def test_不接受全量历史():
    with pytest.raises(SourceError) as excinfo:
        EmMobileSource().fetch_history("110020", limit=None)

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


# ==================== 源类：请求参数与单条返回 ====================


class StubMobileSource(EmMobileSource):
    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        self.calls: list = []

    def _get_json(self, url, **kwargs):
        self.calls.append(kwargs["params"])
        return self.payload


def test_源类带上基金代码且limit大于1仍只返回一条():
    source = StubMobileSource(MOBILE_NORMAL)

    points = source.fetch_history("110020", limit=5)

    assert source.calls[0]["FCODE"] == "110020"
    assert len(points) == 1
    assert points[0].nav_date == date(2026, 10, 16)
