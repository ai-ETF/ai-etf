"""东财单只最近净值源（f10/lsjz）单元测试。

模块名称：server/sources/em_lsjz.py
所测功能：LSJZList 字段映射、货基拒绝、上游错误对象分类、
         limit 截取与分页、`pageSize <= 20` / `MAX_POINTS` 边界。
测试方法：内联两组上游 JSON 样本 + 子类覆盖 `_get_json` 注入分页数据；不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §6.1 坑 2 / Q7。
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from server.sources.em_lsjz import EmLsjzSource, MAX_POINTS, PAGE_SIZE, parse_lsjz_payload
from server.sources.models import FailureKind, SourceError

# 样本组一：普通股票型基金，两行且上游按日期倒序
LSJZ_NORMAL = {
    "ErrCode": 0,
    "Data": {
        "FundType": "001",
        "LSJZList": [
            {"FSRQ": "2026-10-16", "DWJZ": "1.7219", "LJJZ": "1.8219", "JZZZL": "0.13"},
            {"FSRQ": "2026-10-15", "DWJZ": "1.7196", "LJJZ": "1.8196", "JZZZL": "-1.17"},
        ],
    },
}

# 样本组二：可选字段用 `--`/空串占位，且混入非 dict 行与非法日期
LSJZ_PARTIAL = {
    "ErrCode": 0,
    "Data": {
        "FundType": "002",
        "LSJZList": [
            {"FSRQ": "2026-10-14", "DWJZ": "1.0000", "LJJZ": "--", "JZZZL": ""},
            "not-a-dict",
            {"FSRQ": "2026-13-01", "DWJZ": "9.9999"},
        ],
    },
}


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== 正常数据：字段映射 ====================


def test_字段映射并升序排列():
    points = parse_lsjz_payload(LSJZ_NORMAL, "110020", "s", 5)

    assert [p.nav_date for p in points] == [date(2026, 10, 15), date(2026, 10, 16)]
    assert points[-1].unit_nav == Decimal("1.7219")
    assert points[-1].accumulated_nav == Decimal("1.8219")
    assert points[-1].daily_growth == Decimal("0.13")


def test_缺失字段与非法行被跳过():
    points = parse_lsjz_payload(LSJZ_PARTIAL, "110020", "s", 5)

    assert len(points) == 1
    assert points[0].nav_date == date(2026, 10, 14)
    assert points[0].unit_nav == Decimal("1.0000")
    assert points[0].accumulated_nav is None
    assert points[0].daily_growth is None


def test_limit只取最近N条():
    points = parse_lsjz_payload(LSJZ_NORMAL, "110020", "s", 1)

    assert [p.nav_date for p in points] == [date(2026, 10, 16)]


# ==================== 异常：上游错误与货基 ====================


def test_货币基金拒绝而不是把万份收益当净值():
    payload = {
        "ErrCode": 0,
        "Data": {
            "FundType": "005",
            "LSJZList": [{"FSRQ": "2026-10-17", "DWJZ": "0.2190", "LJJZ": "0.8160"}],
        },
    }

    with pytest.raises(SourceError) as excinfo:
        parse_lsjz_payload(payload, "000198", "s", 5)

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST
    assert "万份收益" in excinfo.value.message


def test_200但错误对象记EMPTY_PAYLOAD():
    payload = {"Data": None, "ErrCode": 4, "ErrMsg": "404"}

    with pytest.raises(SourceError) as excinfo:
        parse_lsjz_payload(payload, "110020", "s", 5)

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_Data缺失记EMPTY_PAYLOAD():
    with pytest.raises(SourceError) as excinfo:
        parse_lsjz_payload({"ErrCode": 0}, "110020", "s", 5)

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_净值列表为空记EMPTY_PAYLOAD():
    payload = {"ErrCode": 0, "Data": {"FundType": "001", "LSJZList": []}}

    with pytest.raises(SourceError) as excinfo:
        parse_lsjz_payload(payload, "110020", "s", 5)

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_所有日期都非法记EMPTY_PAYLOAD():
    payload = {
        "ErrCode": 0,
        "Data": {"FundType": "001", "LSJZList": [{"FSRQ": "bad", "DWJZ": "1"}]},
    }

    with pytest.raises(SourceError) as excinfo:
        parse_lsjz_payload(payload, "110020", "s", 5)

    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


# ==================== 边界：能力定位 ====================


@pytest.mark.parametrize("limit", [None, 0, -1, MAX_POINTS + 1])
def test_超出本源定位的limit直接拒绝(limit):
    with pytest.raises(SourceError) as excinfo:
        EmLsjzSource().fetch_history("110020", limit=limit)

    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


# ==================== 分页：两组数据 + 提前结束 ====================


def _page(days):
    return {
        "ErrCode": 0,
        "Data": {
            "FundType": "001",
            "LSJZList": [
                {"FSRQ": d.isoformat(), "DWJZ": "1.0000", "LJJZ": "1.0000", "JZZZL": "0.00"}
                for d in days
            ],
        },
    }


def _days(count):
    return [date(2026, 1, 1) + timedelta(days=index) for index in range(count)]


class StubLsjzSource(EmLsjzSource):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.calls: list = []

    def _get_json(self, url, **kwargs):
        params = kwargs["params"]
        self.calls.append(params)
        return self.pages[params["pageIndex"] - 1]


def test_超过一页时按页拉取并去重排序():
    days = _days(40)
    source = StubLsjzSource([_page(days[20:40]), _page(days[0:20])])

    points = source.fetch_history("110020", limit=30)

    assert len(source.calls) == 2
    assert [call["pageIndex"] for call in source.calls] == [1, 2]
    assert all(call["pageSize"] == PAGE_SIZE for call in source.calls)
    assert len(points) == 30
    assert points[0].nav_date == days[10]
    assert points[-1].nav_date == days[39]


def test_单页足够时只请求一次():
    days = _days(40)
    source = StubLsjzSource([_page(days[20:40])])

    points = source.fetch_history("110020", limit=20)

    assert len(source.calls) == 1
    assert len(points) == 20
    assert points[-1].nav_date == days[39]


def test_短页说明已到末尾提前结束():
    days = _days(40)
    source = StubLsjzSource([_page(days[20:28])])

    points = source.fetch_history("110020", limit=30)

    assert len(source.calls) == 1
    assert len(points) == 8
