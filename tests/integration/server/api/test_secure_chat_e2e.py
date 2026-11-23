"""P1-5 API 端到端：/api/secure-chat/* 路由 ↔ Supabase Auth（真实注册/登录）。

模块名称：认证与对话 API 路由
所测功能：真实 Supabase Auth 注册 → 登录 → 重复注册 409 的完整纵向切片
使用的测试方法：TestClient + 真实 app + 本地 Supabase（gotrue）+ admin 清理
"""
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def registered_user(api_client, sql_delete_auth_user):
    """通过 /api/secure-chat/register 注册真实用户，测试后 SQL 直删（sign_up 用户 admin.delete_user 会报 User not allowed）。"""
    email = f"test-{uuid.uuid4()}@example.com"
    password = "test-password-123"
    resp = api_client.post("/api/secure-chat/register", json={"email": email, "password": password})
    assert resp.status_code == 200, f"注册失败: {resp.text}"
    body = resp.json()
    yield {
        "email": email,
        "password": password,
        "user_id": body["user_id"],
        "token": body.get("access_token"),
    }
    sql_delete_auth_user(body["user_id"])


def test_注册_自动登录返回token(registered_user):
    assert registered_user["token"], "auto-confirm 模式应返回 access_token"
    assert registered_user["user_id"]


def test_登录_返回token且user_id一致(api_client, registered_user):
    resp = api_client.post(
        "/api/secure-chat/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]
    assert resp.json()["user_id"] == registered_user["user_id"]


def test_重复注册_返回409(api_client, registered_user):
    resp = api_client.post(
        "/api/secure-chat/register",
        json={"email": registered_user["email"], "password": "test-password-123"},
    )
    assert resp.status_code == 409


def test_登录_密码错误返回401(api_client, registered_user):
    resp = api_client.post(
        "/api/secure-chat/login",
        json={"email": registered_user["email"], "password": "wrong-password"},
    )
    assert resp.status_code == 401
