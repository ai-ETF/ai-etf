"""源解析纯函数单测（内嵌上游样本，不联网）。

重点覆盖设计文档 §6.1 的三个坑：

1. `em_fund_jjjz` 的列名/日期来自 `showday`，不按下标写死日期；
2. 货基 `DWJZ/LJJZ` 语义不同，必须拒绝而不是当净值；
3. 跨源字段（`RZDF` vs `JZZZL`）映射正确。
"""
from datetime import date
from decimal import Decimal

import pytest

from server.sources import em_fund_jjjz, em_lsjz, em_mobile, em_pingzhongdata
from server.sources.models import FailureKind, SourceError


def _kind(excinfo) -> FailureKind:
    return excinfo.value.kind


# ==================== em_pingzhongdata ====================

PINGZHONGDATA = (
    'var fS_name = "测试联接A";'
    'var Data_netWorthTrend = ['
    '{"x":1791993600000,"y":1.7196,"equityReturn":-1.17,"unitMoney":""},'
    '{"x":1792080000000,"y":1.7219,"equityReturn":0.13,"unitMoney":""}'
    '];'
    'var Data_ACWorthTrend = [[1791993600000,1.8196],[1792080000000,1.8219]];'
)


def test_pingzhongdata_单位与累计净值一次解析并按日期合并():
    points = em_pingzhongdata.parse_pingzhongdata(PINGZHONGDATA, "110020", "s")

    assert [p.nav_date for p in points] == [date(2026, 10, 15), date(2026, 10, 16)]
    assert points[0].unit_nav == Decimal("1.7196")
    assert points[0].accumulated_nav == Decimal("1.8196")
    assert points[1].unit_nav == Decimal("1.7219")
    assert points[1].accumulated_nav == Decimal("1.8219")
    assert points[1].daily_growth == Decimal("0.13")


def test_pingzhongdata_limit取最近N条():
    points = em_pingzhongdata.parse_pingzhongdata(
        PINGZHONGDATA, "110020", "s", limit=1
    )
    assert len(points) == 1
    assert points[0].nav_date == date(2026, 10, 16)


def test_pingzhongdata_货币基金拒绝而不是当净值():
    text = 'var fS_name = "天弘余额宝货币";var something=1;'
    with pytest.raises(SourceError) as excinfo:
        em_pingzhongdata.parse_pingzhongdata(text, "000198", "s")
    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


def test_pingzhongdata_格式漂移记SCHEMA_DRIFT():
    with pytest.raises(SourceError) as excinfo:
        em_pingzhongdata.parse_pingzhongdata(
            'var fS_name = "测试基金";', "110020", "s"
        )
    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


# ==================== em_fund_jjjz ====================

JJJZ = (
    "var db={chars:[\"0\"],datas:["
    '["110020","测试联接A","CS","1.7219","1.8219","1.7196","1.8196",'
    '"0.0023","0.13","开放申购","开放赎回","","1","0","1","","1","0.10%","0.10%","1","1.00%"],'
    '["000000","空净值","K","","","","","","0","暂停申购","暂停赎回","","1","0","1","","1","","","",""]'
    '],count:["1"],record:"2",showday:["2026-10-16","2026-10-15"]}'
)


def test_jjjz按showday解析两天的点(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)

    result = em_fund_jjjz.parse_batch_payload(JJJZ, {"110020"}, "s")

    points = result["110020"]
    assert [p.nav_date for p in points] == [date(2026, 10, 16), date(2026, 10, 15)]
    assert points[0].unit_nav == Decimal("1.7219")
    assert points[0].accumulated_nav == Decimal("1.8219")
    assert points[0].daily_growth == Decimal("0.13")
    assert points[1].unit_nav == Decimal("1.7196")
    assert points[1].daily_growth is None  # T-1 不臆造增长率
    assert "000000" not in result  # 净值为空的行被过滤


def test_jjjz行数明显偏少记SCHEMA_DRIFT():
    with pytest.raises(SourceError) as excinfo:
        em_fund_jjjz.parse_batch_payload(JJJZ, {"110020"}, "s")
    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


def test_jjjz缺少showday记SCHEMA_DRIFT(monkeypatch):
    monkeypatch.setattr(em_fund_jjjz, "MIN_ROWS", 1)
    text = JJJZ.replace('showday:["2026-10-16","2026-10-15"]', "")
    with pytest.raises(SourceError) as excinfo:
        em_fund_jjjz.parse_batch_payload(text, {"110020"}, "s")
    assert _kind(excinfo) == FailureKind.SCHEMA_DRIFT


# ==================== em_lsjz ====================

LSJZ_NORMAL = {
    "Data": {
        "FundType": "001",
        "LSJZList": [
            {"FSRQ": "2026-10-16", "DWJZ": "1.7219", "LJJZ": "1.7219", "JZZZL": "0.13"},
            {"FSRQ": "2026-10-15", "DWJZ": "1.7196", "LJJZ": "1.7196", "JZZZL": "-1.17"},
        ],
    },
    "ErrCode": 0,
}


def test_lsjz字段映射():
    points = em_lsjz.parse_lsjz_payload(LSJZ_NORMAL, "110020", "s", 5)

    assert [p.nav_date for p in points] == [date(2026, 10, 15), date(2026, 10, 16)]
    assert points[-1].unit_nav == Decimal("1.7219")
    assert points[-1].accumulated_nav == Decimal("1.7219")
    assert points[-1].daily_growth == Decimal("0.13")


def test_lsjz货基拒绝而不是把万份收益当净值():
    payload = {
        "Data": {
            "FundType": "005",
            "LSJZList": [{"FSRQ": "2026-10-17", "DWJZ": "0.2190", "LJJZ": "0.8160"}],
        },
        "ErrCode": 0,
    }
    with pytest.raises(SourceError) as excinfo:
        em_lsjz.parse_lsjz_payload(payload, "000198", "s", 5)
    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


def test_lsjz_200但错误对象记EMPTY_PAYLOAD():
    payload = {"Data": None, "ErrCode": 4, "ErrMsg": "404"}
    with pytest.raises(SourceError) as excinfo:
        em_lsjz.parse_lsjz_payload(payload, "110020", "s", 5)
    assert _kind(excinfo) == FailureKind.EMPTY_PAYLOAD


def test_lsjz_不接受全量历史():
    source = em_lsjz.EmLsjzSource()
    with pytest.raises(SourceError) as excinfo:
        source.fetch_history("110020", limit=None)
    assert _kind(excinfo) == FailureKind.INVALID_REQUEST


# ==================== em_mobile ====================

MOBILE_NORMAL = {
    "Datas": {
        "FCODE": "110020",
        "FTYPE": "指数型-股票",
        "FSRQ": "2026-10-16",
        "DWJZ": "1.7219",
        "LJJZ": "1.7219",
        "RZDF": "0.13",
    },
    "ErrCode": 0,
    "Success": True,
}


def test_mobile字段映射_日增长率用RZDF():
    point = em_mobile.parse_mobile_payload(MOBILE_NORMAL, "110020", "s")

    assert point.nav_date == date(2026, 10, 16)
    assert point.unit_nav == Decimal("1.7219")
    assert point.daily_growth == Decimal("0.13")


def test_mobile货基拒绝():
    payload = {
        "Datas": {"FTYPE": "货币型", "FSRQ": "2026-10-17", "DWJZ": "0.2190"},
        "ErrCode": 0,
        "Success": True,
    }
    with pytest.raises(SourceError) as excinfo:
        em_mobile.parse_mobile_payload(payload, "000198", "s")
    assert _kind(excinfo) == FailureKind.INVALID_REQUEST
