"""akshare 调用超时兜底单元测试。

模块名称：server/sources/akshare_util.py
所测功能：`run_akshare_with_timeout` 的成功透传、超时转 `TIMEOUT`、
         `SourceError` 原样透传、其它异常收敛为 `CONNECTION_ERROR`。
测试方法：传入会阻塞/抛异常的普通函数，用 `threading.Event` 控制阻塞时长；
         不导入 akshare、不联网。

设计依据：`docs/20-设计/行情/数据源多源适配器.md` §4.5 硬约束 3。
"""
import threading

import pytest

from server.sources.akshare_util import run_akshare_with_timeout
from server.sources.models import FailureKind, SourceError


def test_成功时原样返回结果():
    def load():
        return {"rows": 8797}

    assert run_akshare_with_timeout("sina_trade_date", 1.0, load) == {"rows": 8797}


def test_超时转成TIMEOUT():
    release = threading.Event()

    def slow():
        release.wait(5)
        return "late"

    try:
        with pytest.raises(SourceError) as excinfo:
            run_akshare_with_timeout("sina_trade_date", 0.05, slow)
    finally:
        release.set()

    assert excinfo.value.kind is FailureKind.TIMEOUT
    assert "0.05s" in excinfo.value.message
    assert "无法被强制终止" in excinfo.value.message


def test_SourceError原样透传():
    original = SourceError("sina_trade_date", FailureKind.SCHEMA_DRIFT, "格式变了")

    def load():
        raise original

    with pytest.raises(SourceError) as excinfo:
        run_akshare_with_timeout("sina_trade_date", 1.0, load)

    assert excinfo.value is original


def test_内部异常收敛为CONNECTION_ERROR():
    def load():
        raise RuntimeError("hk_js_decode failed")

    with pytest.raises(SourceError) as excinfo:
        run_akshare_with_timeout("sina_trade_date", 1.0, load)

    assert excinfo.value.kind is FailureKind.CONNECTION_ERROR
    assert "RuntimeError" in excinfo.value.message
