"""多源适配器结构化事件日志单元测试。

模块名称：server/sources/events.py
所测功能：五类事件（source_result / batch_empty / domain_state / source_switch /
         all_sources_failed）的 JSON 可解析性、字段完整性与日志级别。
测试方法：`caplog` 捕获 logging 输出，`json.loads` 解析 message；不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §7.1–§7.3。
"""
import json
import logging
from datetime import datetime, timedelta

from server.sources import events


def _last_record(caplog):
    record = caplog.records[-1]
    return record, json.loads(record.message)


# ==================== source_result ====================


def test_成功结果记DEBUG且字段完整(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_source_result(
            capability="history",
            source="em_pingzhongdata",
            domain="fund.eastmoney.com",
            ok=True,
            elapsed_ms=160,
            code="110020",
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.DEBUG
    assert payload["event"] == "source_result"
    assert payload["capability"] == "history"
    assert payload["source"] == "em_pingzhongdata"
    assert payload["domain"] == "fund.eastmoney.com"
    assert payload["ok"] is True
    assert payload["elapsed_ms"] == 160
    assert payload["code"] == "110020"
    assert payload["kind"] is None


def test_失败结果记WARNING并带失败分类(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_source_result(
            capability="history_recent",
            source="em_lsjz",
            domain="api.fund.eastmoney.com",
            ok=False,
            elapsed_ms=15000,
            kind="TIMEOUT",
            error="ReadTimeout(...)",
            code="110020",
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.WARNING
    assert payload["ok"] is False
    assert payload["kind"] == "TIMEOUT"
    assert payload["error"] == "ReadTimeout(...)"


def test_未包装异常记ERROR并附堆栈(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        try:
            raise ValueError("解析代码 bug")
        except ValueError:
            events.log_source_result(
                capability="history",
                source="em_pingzhongdata",
                domain="fund.eastmoney.com",
                ok=False,
                elapsed_ms=3,
                kind="UNEXPECTED",
                error="ValueError: 解析代码 bug",
                code="110020",
                exc_info=True,
            )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert payload["kind"] == "UNEXPECTED"
    assert payload["ok"] is False


def test_时间戳为北京时间ISO格式(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_source_result(
            capability="history",
            source="s",
            domain="d",
            ok=True,
            elapsed_ms=1,
        )

    _, payload = _last_record(caplog)
    parsed = datetime.fromisoformat(payload["ts"])
    assert parsed.utcoffset() == timedelta(hours=8)


# ==================== batch_empty ====================


def test_批量零命中记WARNING并带样本(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_batch_empty(
            capability="batch",
            source="em_fund_jjjz",
            domain="fund.eastmoney.com",
            requested=3,
            returned=1,
            sample=["110020", "000001", "005827"],
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.WARNING
    assert payload["event"] == "batch_empty"
    assert payload["capability"] == "batch"
    assert payload["source"] == "em_fund_jjjz"
    assert payload["domain"] == "fund.eastmoney.com"
    assert payload["requested"] == 3
    assert payload["returned"] == 1
    assert payload["sample"] == ["110020", "000001", "005827"]


# ==================== domain_state ====================


def test_熔断记ERROR并带触发原因(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_domain_state(
            domain="fund.eastmoney.com",
            from_state="closed",
            to_state="open",
            consecutive_failures=3,
            cooldown_until=1060.0,
            trigger="TIMEOUT",
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.ERROR
    assert payload["event"] == "domain_state"
    assert payload["from"] == "closed"
    assert payload["to"] == "open"
    assert payload["consecutive_failures"] == 3
    assert payload["cooldown_until"] == 1060.0
    assert payload["trigger"] == "TIMEOUT"


def test_半开与恢复记WARNING并带试探源(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_domain_state(
            domain="fund.eastmoney.com",
            from_state="open",
            to_state="half_open",
            consecutive_failures=3,
            probe_source="em_pingzhongdata",
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.WARNING
    assert payload["to"] == "half_open"
    assert payload["probe_source"] == "em_pingzhongdata"


# ==================== source_switch / all_sources_failed ====================


def test_换源记WARNING并保留已试列表(caplog):
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_source_switch(
            capability="history",
            from_source="em_pingzhongdata",
            to_source="em_lsjz",
            reason="TIMEOUT",
            tried=["em_pingzhongdata"],
            code="110020",
        )

    record, payload = _last_record(caplog)
    assert record.levelno == logging.WARNING
    assert payload["event"] == "source_switch"
    assert payload["from"] == "em_pingzhongdata"
    assert payload["to"] == "em_lsjz"
    assert payload["reason"] == "TIMEOUT"
    assert payload["tried"] == ["em_pingzhongdata"]


def test_全部失败记ERROR且保留结构化tried(caplog):
    tried = [
        {"source": "em_pingzhongdata", "kind": "TIMEOUT", "error": "15s"},
        {"source": "em_lsjz", "kind": "EMPTY_PAYLOAD", "error": "空"},
    ]
    with caplog.at_level(logging.DEBUG, logger="server.sources.events"):
        events.log_all_sources_failed("history", tried, code="110020")

    record, payload = _last_record(caplog)
    assert record.levelno == logging.ERROR
    assert payload["event"] == "all_sources_failed"
    assert payload["capability"] == "history"
    assert payload["code"] == "110020"
    assert payload["tried"] == tried
