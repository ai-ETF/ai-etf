"""auth_service 单元测试：注册/退出/注销的校验与异常映射。

模块名称：server/services/auth_service.py
所测功能：validate_email、validate_password（参数校验）、register_user（注册成功/邮箱已存在/校验失败）、
         logout_user（撤销 token + 登出）、delete_account（密码复核后注销）
测试方法：monkeypatch get_supabase / revoke，用 FakeSupabase 替身覆盖 auth/rpc 子接口，全程不联网、不连 Supabase。
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

import server.services.auth_service as auth_service
from server.services.auth_service import (
    delete_account,
    logout_user,
    register_user,
    validate_email,
    validate_password,
)


# ==================== 替身：模拟 Supabase client ====================


class FakeSignUpResult:
    def __init__(self, user=None, session=None):
        self.user = user
        self.session = session


class FakeAdmin:
    def __init__(self, client):
        self._c = client

    def sign_out(self, token, scope):
        if self._c.sign_out_error:
            raise self._c.sign_out_error
        self._c.signed_out.append((token, scope))

    def delete_user(self, user_id):
        if self._c.delete_user_error:
            raise self._c.delete_user_error
        self._c.deleted_users.append(user_id)


class FakeAuth:
    def __init__(self, client):
        self._c = client
        self.admin = FakeAdmin(client)

    def sign_up(self, credentials):
        if self._c.sign_up_error:
            raise self._c.sign_up_error
        return self._c.sign_up_result

    def sign_in_with_password(self, credentials):
        if self._c.sign_in_error:
            raise self._c.sign_in_error
        return object()


class FakeRpc:
    def __init__(self, client):
        self._c = client

    def execute(self):
        if self._c.rpc_error:
            raise self._c.rpc_error
        return object()


class FakeSupabase:
    """覆盖 auth_service 用到的 auth/rpc 子接口，不产生任何网络/DB IO。"""

    def __init__(self):
        self.auth = FakeAuth(self)
        self.sign_up_result = None
        self.sign_up_error = None
        self.sign_in_error = None
        self.sign_out_error = None
        self.rpc_error = None
        self.delete_user_error = None
        self.signed_out = []
        self.deleted_users = []
        self.rpc_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return FakeRpc(self)


@pytest.fixture
def fake_supabase():
    return FakeSupabase()


def _patch_supabase(monkeypatch, fake):
    monkeypatch.setattr(auth_service, "get_supabase", lambda: fake)


# ==================== validate_email ====================


def test_合法邮箱_不抛异常():
    validate_email("user@example.com")


def test_非法邮箱_抛400():
    with pytest.raises(HTTPException) as e:
        validate_email("not-an-email")
    assert e.value.status_code == 400


def test_空邮箱_抛400():
    with pytest.raises(HTTPException):
        validate_email("")


# ==================== validate_password ====================


def test_密码8位_通过():
    validate_password("12345678")


def test_密码7位_抛400():
    with pytest.raises(HTTPException) as e:
        validate_password("1234567")
    assert e.value.status_code == 400


def test_空密码_抛400():
    with pytest.raises(HTTPException):
        validate_password("")


# ==================== register_user ====================


def test_注册成功_返回session和user(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_result = FakeSignUpResult(
        user=SimpleNamespace(id="user-123"), session=SimpleNamespace()
    )
    result = register_user("user@example.com", "password123")
    assert result["user"].id == "user-123"
    assert result["session"] is not None


def test_邮箱已存在_抛409(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 422, "user_already_exists")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 409


def test_邮箱格式错误_抛400():
    with pytest.raises(HTTPException) as e:
        register_user("bad-email", "password123")
    assert e.value.status_code == 400


def test_密码过短_抛400():
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "short")
    assert e.value.status_code == 400


def test_注册_数据库未就绪_抛500(monkeypatch):
    monkeypatch.setattr(auth_service, "get_supabase", lambda: None)
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 500


def test_未知异常_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = RuntimeError("boom")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 502


def test_密码过弱_抛400(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthWeakPasswordError("weak", 400, ["reason"])
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 400


def test_email地址无效_抛400(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 400, "email_address_invalid")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 400


def test_弱密码_抛400(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 400, "weak_password")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 400


def test_其他AuthApi错误_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 429, "over_request_rate_limit")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 502


# ==================== logout_user ====================


def test_撤销token并调用supabase登出(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    revoked = []
    monkeypatch.setattr(auth_service, "revoke", lambda t, e: revoked.append((t, e)))

    logout_user("tok-123", 123.0)
    assert revoked == [("tok-123", 123.0)]
    assert fake_supabase.signed_out == [("tok-123", "global")]


def test_数据库未就绪_仍本地撤销不报错(monkeypatch):
    monkeypatch.setattr(auth_service, "get_supabase", lambda: None)
    revoked = []
    monkeypatch.setattr(auth_service, "revoke", lambda t, e: revoked.append((t, e)))

    logout_user("tok-123", 123.0)  # 不抛异常
    assert revoked == [("tok-123", 123.0)]


def test_sign_out抛异常_不阻塞返回(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_out_error = RuntimeError("signout fail")
    monkeypatch.setattr(auth_service, "revoke", lambda t, e: None)

    logout_user("tok-123", 123.0)  # 不抛异常


# ==================== delete_account ====================


def test_注销_数据库未就绪_抛500(monkeypatch):
    monkeypatch.setattr(auth_service, "get_supabase", lambda: None)
    with pytest.raises(HTTPException) as e:
        delete_account("user-1", "user@example.com", "password123")
    assert e.value.status_code == 500


def test_密码错误_抛401(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_in_error = RuntimeError("invalid credentials")
    with pytest.raises(HTTPException) as e:
        delete_account("user-1", "user@example.com", "password123")
    assert e.value.status_code == 401


def test_成功_清理业务数据并删除账号(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    delete_account("user-1", "user@example.com", "password123")  # 不抛异常
    assert fake_supabase.rpc_calls == [("purge_user_data", {"p_user_id": "user-1"})]
    assert fake_supabase.deleted_users == ["user-1"]


def test_清理业务数据失败_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.rpc_error = RuntimeError("rpc fail")
    with pytest.raises(HTTPException) as e:
        delete_account("user-1", "user@example.com", "password123")
    assert e.value.status_code == 502


def test_删除账号失败_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.delete_user_error = RuntimeError("delete fail")
    with pytest.raises(HTTPException) as e:
        delete_account("user-1", "user@example.com", "password123")
    assert e.value.status_code == 502
