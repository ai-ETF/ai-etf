"""冒烟测试：验证能连上本地 Supabase 栈并读写真实表。

模块名称：存储层 ↔ 本地 Supabase（pgvector）
所测功能：service_role 客户端连接、基础表读写往返
使用的测试方法：真实本地 Supabase 栈 + 合成 UUID 数据 + teardown 定向清理
"""
import socket
import uuid

import pytest

pytestmark = pytest.mark.integration


def test_连上本地库且fund_fee_rules表存在(supabase_client):
    """基础连通性：fund_fee_rules 表可查询（含种子数据）。"""
    resp = supabase_client.table("fund_fee_rules").select("count", count="exact").execute()
    assert resp.count >= 20


def test_出网守卫拦截非localhost连接():
    """安全护栏：任何连接非 localhost 地址的尝试都必须被拦截。"""
    with pytest.raises(RuntimeError, match="禁止出网"):
        socket.create_connection(("huggingface.co", 443), timeout=2)


def test_写入并读回再清理(supabase_client):
    """真实读写往返：写入一条合成数据 → 读回 → 清理。"""
    user_id = str(uuid.uuid4())
    watchlist = supabase_client.table("watchlist")

    inserted = watchlist.insert({"user_id": user_id, "fund_code": "510300"}).execute()
    assert inserted.data, "写入失败"

    try:
        fetched = watchlist.select("*").eq("user_id", user_id).execute()
        assert any(row["fund_code"] == "510300" for row in fetched.data), "读回数据不一致"
    finally:
        # 定向清理：失败必须抛错，不得静默
        watchlist.delete().eq("user_id", user_id).execute()
        leftover = watchlist.select("count", count="exact").eq("user_id", user_id).execute()
        assert leftover.count == 0, f"清理失败，残留 {leftover.count} 行"
