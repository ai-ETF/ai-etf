"""P0-4 自选股集成测试：WatchlistService ↔ 真实 Postgres（watchlist 表）。

模块名称：自选股服务
所测功能：真实数据库增删查、应用层查重、清空、多用户隔离
使用的测试方法：本地 Supabase 栈 + 合成 user_id + 注入本地库 client + purge 定向清理
"""
import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration


def test_add_真实写库并读回(watchlist_service, supabase_client, user_id):
    r = watchlist_service.add(user_id, "510300", "沪深300ETF")
    assert r["success"] is True
    assert r["item"]["fund_code"] == "510300"

    # 真实读回
    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 1
    assert rows[0]["fund_code"] == "510300"
    assert rows[0]["fund_name"] == "沪深300ETF"


def test_add_重复添加被拒绝(watchlist_service, user_id):
    assert watchlist_service.add(user_id, "510300", "沪深300ETF")["success"] is True
    r2 = watchlist_service.add(user_id, "510300", "沪深300ETF")
    assert r2["success"] is False
    assert "已" in r2["message"]


def test_remove_真实删库(watchlist_service, supabase_client, user_id):
    watchlist_service.add(user_id, "510300", "沪深300ETF")
    r = watchlist_service.remove(user_id, "510300")
    assert r["success"] is True
    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 0


def test_remove_不存在返回失败(watchlist_service, user_id):
    r = watchlist_service.remove(user_id, "999999")
    assert r["success"] is False


def test_list_不包含行情(watchlist_service, user_id):
    watchlist_service.add(user_id, "510300", "沪深300ETF")
    watchlist_service.add(user_id, "159919", "嘉实沪深300ETF")
    r = watchlist_service.list(user_id, include_quote=False)
    assert r["total"] == 2
    codes = {item["fund_code"] for item in r["items"]}
    assert codes == {"510300", "159919"}


def test_clear_清空(watchlist_service, supabase_client, user_id):
    watchlist_service.add(user_id, "510300", "沪深300ETF")
    watchlist_service.add(user_id, "159919", "嘉实沪深300ETF")
    r = watchlist_service.clear(user_id)
    assert r["success"] is True
    assert r["removed_count"] == 2
    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 0


def test_不同用户数据隔离(watchlist_service, supabase_client, user_id):
    other = str(_uuid.uuid4())
    try:
        watchlist_service.add(user_id, "510300", "沪深300ETF")
        watchlist_service.add(other, "510300", "沪深300ETF")
        # 当前用户列表只有自己的 1 条
        r = watchlist_service.list(user_id, include_quote=False)
        assert r["total"] == 1
    finally:
        # 定向清理 other，失败抛错
        supabase_client.table("watchlist").delete().eq("user_id", other).execute()
