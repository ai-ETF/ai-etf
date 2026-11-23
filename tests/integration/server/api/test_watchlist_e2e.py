"""P1-5 API 端到端：/api/watchlist/* 路由 ↔ 服务层 ↔ 真实 Postgres。

模块名称：自选股 API 路由
所测功能：JWT 鉴权 → 路由 → WatchlistService → 真实 watchlist 表的完整纵向切片
使用的测试方法：TestClient + 真实 app + 本地 Supabase + 自签 JWT + 合成 user_id
"""
import jwt

import pytest

pytestmark = pytest.mark.integration


def _auth_headers(user_id: str, secret: str) -> dict:
    token = jwt.encode(
        {"sub": user_id, "role": "authenticated", "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_无Authorization头_返回422(api_client):
    """Header(...) 是必需参数，缺失时 FastAPI 返回 422（而非 401）。"""
    resp = api_client.get("/api/watchlist/list", params={"include_quote": False})
    assert resp.status_code == 422


def test_无效token_返回401(api_client):
    """Bearer 格式正确但 token 验证失败 → 401。"""
    resp = api_client.get(
        "/api/watchlist/list",
        params={"include_quote": False},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 401


def test_增删查清_端到端(api_client, supabase_client, user_id, jwt_secret):
    headers = _auth_headers(user_id, jwt_secret)

    # 1. 添加
    resp = api_client.post(
        "/api/watchlist/add",
        json={"fund_code": "510300", "fund_name": "沪深300ETF"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 2. 查询（不包含行情，避免触发 AKShare）
    resp = api_client.get("/api/watchlist/list", params={"include_quote": False}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["fund_code"] == "510300"

    # 3. 真实落库验证
    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 1

    # 4. 移除（DELETE 带 body，用 request 方法）
    resp = api_client.request(
        "DELETE", "/api/watchlist/remove",
        json={"fund_code": "510300"}, headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 0


def test_清空_端到端(api_client, supabase_client, user_id, jwt_secret):
    headers = _auth_headers(user_id, jwt_secret)
    for code in ["510300", "159919"]:
        api_client.post(
            "/api/watchlist/add",
            json={"fund_code": code, "fund_name": "测试ETF"},
            headers=headers,
        )

    resp = api_client.request("DELETE", "/api/watchlist/clear", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["removed_count"] == 2

    rows = supabase_client.table("watchlist").select("*").eq("user_id", user_id).execute().data
    assert len(rows) == 0
