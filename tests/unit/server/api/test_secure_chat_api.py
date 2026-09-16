"""secure_chat API 单元测试。

模块名称：server/api/secure_chat.py
所测功能：login / register / logout / delete-account / 会话 CRUD（服务与认证依赖替身）
测试方法：FastAPI TestClient + monkeypatch 服务函数 + dependency_overrides 注入固定 user_id，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.deps import get_current_user
from server.api.secure_chat import router


class FakeSession:
    access_token = "token-123"
    expires_in = 3600


class FakeUser:
    id = "user-123"


class FakeSignInResult:
    session = FakeSession()
    user = FakeUser()


class FakeAuth:
    def sign_in_with_password(self, creds):
        return FakeSignInResult()


class FakeSupabase:
    auth = FakeAuth()


class FakeRepo:
    chats = [{"id": "c1", "user_id": "u1", "title": "t1", "created_at": "2026-01-01", "updated_at": "2026-01-01"}]
    messages = [{"id": "m1", "chat_id": "c1", "role": "user", "content": "hi", "created_at": "2026-01-01"}]

    def list_chats(self, user_id, limit=50):
        return self.chats

    def get_chat(self, chat_id):
        return self.chats[0] if chat_id == "c1" else None

    def get_messages(self, chat_id, limit=100):
        return self.messages

    def delete_chat(self, chat_id):
        return True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("server.api.secure_chat.get_supabase", lambda: FakeSupabase())
    monkeypatch.setattr("server.api.secure_chat.get_chat_repo", lambda: FakeRepo())
    monkeypatch.setattr("server.api.secure_chat.register_user",
                        lambda email, password: {"session": None, "user": None})
    monkeypatch.setattr("server.api.secure_chat.logout_user", lambda token, exp: None)
    monkeypatch.setattr("server.api.secure_chat.delete_account", lambda user_id, email, password: None)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


def test_login(client):
    resp = client.post("/secure-chat/login", json={"email": "u@e.com", "password": "pass12345"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] == "token-123"
    assert data["user_id"] == "user-123"


def test_register_邮箱确认模式(client):
    resp = client.post("/secure-chat/register", json={"email": "u@e.com", "password": "pass12345"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["needs_email_confirmation"] is True


def test_logout(client, monkeypatch):
    monkeypatch.setattr("server.api.secure_chat.extract_and_verify",
                        lambda auth: ("token-123", {"sub": "u1", "exp": 1234567890}))
    resp = client.post("/secure-chat/logout", headers={"Authorization": "Bearer token-123"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_delete_account(client, monkeypatch):
    monkeypatch.setattr("server.api.secure_chat.extract_and_verify",
                        lambda auth: ("token-123", {"sub": "u1", "email": "u@e.com", "exp": 1234567890}))
    resp = client.post("/secure-chat/delete-account", json={"password": "pass12345"},
                       headers={"Authorization": "Bearer token-123"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_list_chats(client):
    resp = client.get("/secure-chat/chats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["chats"][0]["id"] == "c1"


def test_get_messages(client):
    resp = client.get("/secure-chat/chats/c1/messages")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_delete_chat(client):
    resp = client.delete("/secure-chat/chats/c1")
    assert resp.status_code == 200
    assert resp.json()["message"] == "会话已删除"
