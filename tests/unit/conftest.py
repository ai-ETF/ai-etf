"""单元测试公共夹具。

交易日历快照（server/services/trading_calendar.py）是**进程级单例**：不在用例
之间清空，前一个用例注入的假快照会漏给后一个用例，交易日相关断言会互相污染。
需要日历的用例直接调用 `trading_calendar.install_snapshot(...)` 注入数据。
"""
import pytest

from server.services import trading_calendar


@pytest.fixture(autouse=True)
def _重置交易日历快照():
    trading_calendar.reset_cache()
    yield
    trading_calendar.reset_cache()
