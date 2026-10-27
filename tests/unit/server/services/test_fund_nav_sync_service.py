"""fund_nav_sync_service 单元测试：批量更新、单只兜底、历史补齐与写库契约。

模块名称：server/services/fund_nav_sync_service.py
所测功能：`update_batch`（批量源 → 逐点合并 → 单只兜底 → 更新状态）、`ensure_history`、
         `warm_positions`、`describe`、写库只走 RPC
测试方法：内存 FakeClient 记录 RPC 调用与参数、FakeRouter 造上游结果；不联网、不连 Supabase。

必须守住的三条契约：
1. **不写 0/空净值**（R10）：无效点丢弃，绝不落库冒充数据；
2. **失败只写 `last_error`**：不动 `latest_*`，库中旧值永远保留；
3. **写库只走 RPC**：应用层不拼 upsert，`merge_fund_nav` 保证「改值 + 更正」原子。
"""
import fcntl
import os
from datetime import date
from decimal import Decimal

import pytest

from server.services import fund_nav_sync_service as sync_module
from server.services.fund_nav_sync_service import (
    MERGE_BATCH_SIZE,
    FundNavSyncService,
    NavLockBusy,
    nav_update_lock,
)
from server.sources.models import AllSourcesFailed, NavPoint


class _FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _FakeTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._eq = []
        self._limit = None
        self._range = None

    def select(self, fields=None, count=None):
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def in_(self, column, values):
        return self

    def gt(self, column, value):
        return self

    def gte(self, column, value):
        return self

    def order(self, column, desc=False):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = list(self.store["rows"].get(self.name, []))
        for column, value in self._eq:  # 只实现等值过滤；gt/in 由用例直接配置目标行
            rows = [r for r in rows if str(r.get(column)) == str(value)]
        total = len(rows)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        elif self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResult(rows, count=total)


class _FakeRpc:
    def __init__(self, store, name, params):
        self.store = store
        self.name = name
        self.params = params

    def execute(self):
        self.store["rpcs"].append((self.name, self.params))
        return _FakeResult(self.store["rpc_results"].get(self.name))


class _FakeClient:
    def __init__(self, rows=None, rpc_results=None):
        self.store = {
            "rows": rows or {},
            "rpcs": [],
            "rpc_results": rpc_results or {},
        }

    def table(self, name):
        return _FakeTable(self.store, name)

    def rpc(self, name, params):
        return _FakeRpc(self.store, name, params)

    def calls(self, name):
        return [params for rpc, params in self.store["rpcs"] if rpc == name]


class _FakeRouter:
    def __init__(self, batch=None, latest=None, history=None, recent=None,
                 fail_latest=None, fail_history=None):
        self.batch = batch or {}
        self.latest = latest or {}
        self.history = history or {}
        self.recent = recent or {}
        self.fail_latest = fail_latest or set()
        self.fail_history = fail_history or set()
        self.downloads = []

    def fetch_latest_batch(self, codes):
        return self.batch

    def fetch_latest(self, code):
        if code in self.fail_latest:
            raise AllSourcesFailed("latest", [{"source": "em_lsjz", "kind": "http", "error": "boom"}])
        return self.latest[code]

    def fetch_history(self, code):
        self.downloads.append(code)
        if code in self.fail_history:
            raise AllSourcesFailed("history", [{"source": "em_lsjz", "kind": "http", "error": "boom"}])
        return self.history.get(code, [])

    def fetch_history_recent(self, code, limit):
        return self.recent.get(code, [])


def _point(code="110020", nav_date="2026-10-23", unit="1.7626", source="em_lsjz"):
    return NavPoint(
        fund_code=code,
        nav_date=date.fromisoformat(nav_date),
        unit_nav=Decimal(unit) if unit is not None else None,
        accumulated_nav=Decimal(unit) if unit is not None else None,
        daily_growth=Decimal("0.1"),
        source=source,
    )


# ==================== 批量更新 ====================


def test_批量命中为主_未命中的代码走单只兜底():
    client = _FakeClient(
        rpc_results={"merge_fund_nav": [{"inserted": 1, "updated": 0, "revised": 0}]}
    )
    router = _FakeRouter(
        batch={"110020": [_point()]},
        latest={"000008": _point("000008")},
    )

    result = FundNavSyncService(client=client, router=router).update_batch(
        ["110020", "000008"], use_lock=False
    )

    assert (result.codes, result.batch_hit, result.single_fallback) == (2, 1, 1)
    assert result.unmatched == 1
    assert result.inserted == 2  # 批量 1 行 + 兜底 1 行，各一次 RPC
    # 每只命中的基金都要更新最新净值投影
    states = client.calls("upsert_fund_nav_state")
    assert {s["p_fund_code"] for s in states} == {"110020", "000008"}
    assert all(s["p_got_data"] is True for s in states)


def test_零净值与空净值点被丢弃不落库():
    """R10：宁可保留旧值，也不用 0 填充。"""
    client = _FakeClient()
    router = _FakeRouter(batch={"110020": [_point(unit="0"), _point(unit=None)]})

    result = FundNavSyncService(client=client, router=router).update_batch(
        ["110020"], use_lock=False
    )

    assert result.batch_hit == 0
    assert client.calls("merge_fund_nav") == []


def test_单只兜底失败只记错误不影响其余基金():
    client = _FakeClient()
    router = _FakeRouter(
        batch={},
        latest={"000008": _point("000008")},
        fail_latest={"110020"},
    )

    result = FundNavSyncService(client=client, router=router).update_batch(
        ["110020", "000008"], use_lock=False
    )

    assert result.failed == 1 and result.single_fallback == 1
    assert "110020" in result.failures
    error_state = [
        p for p in client.calls("upsert_fund_nav_state")
        if p["p_fund_code"] == "110020"
    ][0]
    assert "boom" in error_state["p_error"]
    # 失败只写 last_error，不动最新净值
    assert error_state["p_latest_nav_date"] is None
    assert error_state["p_got_data"] is False


def test_白名单为空时直接返回不触网():
    client = _FakeClient()
    router = _FakeRouter()

    result = FundNavSyncService(client=client, router=router).update_batch(
        [], use_lock=False
    )

    assert result.codes == 0
    assert client.store["rpcs"] == []


def test_已有更新在跑时抛NavLockBusy(tmp_path, monkeypatch):
    """单飞锁：拿不到锁 = 本轮跳过，不算失败；由调用方决定日志级别。"""
    lock_path = str(tmp_path / "nav.lock")
    monkeypatch.setattr(sync_module, "NAV_UPDATE_LOCK_PATH", lock_path)

    holder = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(NavLockBusy):
            with nav_update_lock():
                pass
    finally:
        os.close(holder)


# ==================== 历史补齐 ====================


def test_历史已ready时跳过且不触网():
    client = _FakeClient({"fund_nav_state": [{"fund_code": "110020",
                                              "history_status": "ready",
                                              "history_start_date": "2011-05-06"}]})
    router = _FakeRouter(history={"110020": [_point()]})

    fill = FundNavSyncService(client=client, router=router).ensure_history("110020")

    assert fill.status == "skipped"
    assert router.downloads == []
    assert client.store["rpcs"] == []


def test_历史补齐成功写入状态与起止范围():
    client = _FakeClient(rpc_results={"merge_fund_nav": [{"inserted": 2, "updated": 0, "revised": 0}]})
    router = _FakeRouter(history={"110020": [
        _point(nav_date="2011-05-06", unit="1.0"),
        _point(nav_date="2026-10-23"),
    ]})

    fill = FundNavSyncService(client=client, router=router).ensure_history("110020")

    assert (fill.status, fill.inserted, fill.start_date) == ("ready", 2, date(2011, 5, 6))
    state = client.calls("upsert_fund_nav_state")[-1]
    assert state["p_history_status"] == "ready"
    assert state["p_history_start_date"] == "2011-05-06"
    assert state["p_latest_nav_date"] == "2026-10-23"


def test_上游全失败时状态置failed并保留原因():
    client = _FakeClient()
    router = _FakeRouter(fail_history={"110020"})

    fill = FundNavSyncService(client=client, router=router).ensure_history("110020")

    assert fill.status == "failed"
    state = client.calls("upsert_fund_nav_state")[-1]
    assert state["p_history_status"] == "failed"
    assert "boom" in state["p_error"]


def test_上游返回空净值不落库且置failed():
    client = _FakeClient()
    router = _FakeRouter(history={"110020": [_point(unit=None)]})

    fill = FundNavSyncService(client=client, router=router).ensure_history("110020")

    assert fill.status == "failed"
    assert client.calls("merge_fund_nav") == []


# ==================== 缺口修复 ====================


def test_repair优先用近端数据补齐缺口():
    """确认日取不到净值时先拉近 20 条，命中即止，不下全量（省 452 KB/次）。"""
    client = _FakeClient()
    router = _FakeRouter(recent={"110020": [_point()]})

    lookup = FundNavSyncService(client=client, router=router).repair(
        "110020", date(2026, 10, 23)
    )

    assert lookup.status.value == "ok"
    assert router.downloads == []  # 没有触发全量下载
    assert client.calls("merge_fund_nav")


def test_repair近端未命中时转全量再回读():
    client = _FakeClient({
        "fund_nav": [{"fund_code": "110020", "nav_date": "2026-10-20",
                      "unit_nav": Decimal("1.75"), "accumulated_nav": Decimal("1.75"),
                      "daily_growth": None, "source": "em_lsjz"}],
    })
    router = _FakeRouter(
        recent={"110020": [_point(nav_date="2026-10-23")]},
        history={"110020": [_point(nav_date="2026-10-20", unit="1.75")]},
    )

    lookup = FundNavSyncService(client=client, router=router).repair(
        "110020", date(2026, 10, 20)
    )

    assert router.downloads == ["110020"]
    assert lookup.status.value == "ok"
    assert lookup.point.nav_date == date(2026, 10, 20)


# ==================== 持仓预热 ====================


def test_持仓预热跳过已ready的基金():
    client = _FakeClient({
        "positions": [{"fund_code": "110020"}, {"fund_code": "000008"}],
        "fund_nav_state": [{"fund_code": "110020", "history_status": "ready"}],
    })
    router = _FakeRouter(history={"000008": [_point("000008")]})

    results = FundNavSyncService(client=client, router=router).warm_positions(pause=0)

    assert [r.fund_code for r in results] == ["000008"]
    assert router.downloads == ["000008"]


# ==================== 写库契约 ====================


def test_超过500行按批拆分调用RPC():
    """单次 RPC 不超过 500 行（存储设计 §4.4.2），避免一次事务撑爆。"""
    client = _FakeClient(rpc_results={"merge_fund_nav": [{"inserted": 1, "updated": 0, "revised": 0}]})
    rows = [{"fund_code": "110020", "nav_date": "2026-10-23"} for _ in range(MERGE_BATCH_SIZE + 1)]

    inserted, _, _ = FundNavSyncService(client=client)._merge(rows)

    assert len(client.calls("merge_fund_nav")) == 2
    assert inserted == 2


def test_状态更新只走RPC不在应用层拼upsert():
    client = _FakeClient()
    router = _FakeRouter(batch={"110020": [_point()]})

    FundNavSyncService(client=client, router=router).update_batch(["110020"], use_lock=False)

    assert all(name in ("merge_fund_nav", "upsert_fund_nav_state")
               for name, _ in client.store["rpcs"])


# ==================== 观测 ====================


def test_describe汇总历史状态与最近失败():
    client = _FakeClient({
        "fund_nav_state": [
            {"fund_code": "110020", "history_status": "ready", "last_checked_at": "2026-10-23T20:06:00"},
            {"fund_code": "000008", "history_status": "failed", "last_checked_at": "2026-10-22T20:06:00",
             "last_error": "boom"},
        ],
        "fund_nav": [{"fund_code": "110020"}],
    })

    stats = FundNavSyncService(client=client).describe()

    assert stats["funds_tracked"] == 2
    assert stats["by_status"] == {"ready": 1, "failed": 1}
    assert stats["nav_rows"] == 1
    assert [e["fund_code"] for e in stats["recent_failures"]] == ["000008"]
    assert stats["last_checked_at"] == "2026-10-23T20:06:00"
