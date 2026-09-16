"""app 生命周期（lifespan）单元测试（N 类基础设施，借 API conftest 的 langchain 替身使 server.app 可轻量导入）。

模块名称：server/app.py
所测功能：lifespan（Supabase 校验 + 调度器启停钩子）
测试方法：monkeypatch get_supabase / start_scheduler / shutdown_scheduler，全程不联网、不连 Supabase。
"""
import pytest


@pytest.mark.asyncio
async def test_lifespan_正常启动与关闭(monkeypatch):
    from server.app import lifespan

    calls = []
    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: object())
    monkeypatch.setattr("server.services.spot_cache_scheduler.start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr("server.services.spot_cache_scheduler.shutdown_scheduler", lambda: calls.append("shutdown"))

    async with lifespan(None):
        assert calls == ["start"]
    assert calls == ["start", "shutdown"]


@pytest.mark.asyncio
async def test_lifespan_Supabase连接失败_抛错(monkeypatch):
    from server.app import lifespan

    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: None)
    monkeypatch.setattr("server.services.spot_cache_scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("server.services.spot_cache_scheduler.shutdown_scheduler", lambda: None)

    with pytest.raises(RuntimeError, match="Supabase连接失败"):
        async with lifespan(None):
            pass
