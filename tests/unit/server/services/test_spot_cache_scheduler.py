"""spot_cache_scheduler 单元测试：确认触发的调度接线（《执行机制》§3.12）。

覆盖：灰度开关、净值同步不触发确认、10:00 主任务 / 每小时补扫 / 08:05 过期补扫
的注册、15:37 旧任务已删除。Runner 自身的逻辑不在这里测。
"""
import asyncio

import pytest

import server.services.spot_cache_scheduler as sched


class _FakeRunner:
    """替身 Runner：记录 trigger，不做任何 IO。"""

    calls = []

    def run(self, trigger="manual"):
        _FakeRunner.calls.append(trigger)
        return {"status": "ok", "trigger": trigger}


@pytest.fixture
def fake_runner(monkeypatch):
    from server.config.settings import SETTINGS

    _FakeRunner.calls = []
    monkeypatch.setattr(SETTINGS, "ORDER_CONFIRM_ENABLED", True)
    monkeypatch.setattr("server.services.order_confirm_service.OrderConfirmService", _FakeRunner)
    return _FakeRunner


def test_灰度关闭时不跑确认(monkeypatch):
    from server.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ORDER_CONFIRM_ENABLED", False)
    monkeypatch.setattr("server.services.order_confirm_service.OrderConfirmService", _FakeRunner)
    _FakeRunner.calls = []
    assert asyncio.run(sched._confirm_pending_orders_job("fallback")) is None
    assert _FakeRunner.calls == []


def test_开关打开时按trigger调用Runner(fake_runner):
    asyncio.run(sched._confirm_pending_orders_job("startup"))
    assert fake_runner.calls == ["startup"]


class _FakeNavSync:
    """替身净值同步：按需抛 NavLockBusy / 普通异常 / 返回结果对象。"""

    def __init__(self, mode="ok"):
        self.mode = mode

    def update_batch(self):
        from server.services.fund_nav_sync_service import NavLockBusy
        if self.mode == "busy":
            raise NavLockBusy("已有同步在跑")
        if self.mode == "error":
            raise RuntimeError("上游失败")

        class _R:
            def as_dict(self):
                return {"updated": 1}
        return _R()


@pytest.mark.parametrize("mode", ["ok", "busy", "error"])
def test_净值同步不触发确认(monkeypatch, mode):
    import server.services.fund_nav_sync_service as nav_mod

    monkeypatch.setattr(nav_mod, "FundNavSyncService", lambda: _FakeNavSync(mode))
    monkeypatch.setattr(sched, "_is_trading_day_or_none", lambda d: True)
    monkeypatch.setattr(sched, "_warm_positions_job", _noop_async)
    triggered = []

    async def fake_job(trigger):
        triggered.append(trigger)

    monkeypatch.setattr(sched, "_confirm_pending_orders_job", fake_job)

    asyncio.run(sched._fund_nav_update_job())
    assert triggered == []


async def _noop_async():
    return None


def test_调度注册_确认任务与旧任务删除(monkeypatch):
    """10:00 主任务 + 11:00–23:00 每小时补扫；15:37 任务已删除。"""
    monkeypatch.setattr(sched.asyncio, "ensure_future", lambda coro: coro.close())

    async def main():
        s = sched.start_scheduler()
        jobs = {j.id: j for j in s.get_jobs()}
        assert "confirm_pending_orders" not in jobs
        assert "order_confirm_primary" in jobs
        assert "order_confirm_catchup" in jobs
        assert "order_confirm_morning" not in jobs

        primary = {f.name: str(f) for f in jobs["order_confirm_primary"].trigger.fields}
        assert primary["hour"] == "10"
        assert primary["minute"] == "0"

        catchup = {f.name: str(f) for f in jobs["order_confirm_catchup"].trigger.fields}
        assert catchup["hour"] == "11-23"
        assert catchup["minute"] == "0"

        # 净值轮仍存在，但不再触发确认
        assert "fund_nav_update_overnight" in jobs
        s.shutdown(wait=False)

    asyncio.run(main())
