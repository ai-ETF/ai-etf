"""auth_service 单元测试：注册/刷新/退出/注销的校验与异常映射。

模块名称：server/services/auth_service.py
所测功能：validate_email、validate_password（参数校验）、register_user（注册成功/邮箱已存在/校验失败）、
         refresh_session_token（刷新登录态/凭证失效/异常映射）、
         logout_user（撤销 token + 登出）、delete_account（密码复核后注销）
测试方法：monkeypatch get_supabase / revoke，用 FakeSupabase 替身覆盖 auth/rpc 子接口，全程不联网、不连 Supabase。
"""
import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from supabase_auth.errors import (
    AuthApiError,
    AuthRetryableError,
    AuthSessionMissingError,
    AuthWeakPasswordError,
)

import server.services.auth_service as auth_service
from server.services.auth_service import (
    delete_account,
    logout_user,
    refresh_session_token,
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

    def refresh_session(self, refresh_token=None):
        self._c.refresh_calls.append(refresh_token)
        if self._c.refresh_error:
            raise self._c.refresh_error
        return self._c.refresh_result


class FakeRpc:
    def __init__(self, client, name):
        self._c = client
        self._name = name

    def execute(self):
        err = self._c.rpc_errors.get(self._name)
        if err:
            raise err
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
        self.refresh_result = None
        self.refresh_error = None
        self.refresh_calls = []
        self.rpc_error = None
        self.rpc_errors = {}
        self.delete_user_error = None
        self.signed_out = []
        self.deleted_users = []
        self.rpc_calls = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return FakeRpc(self, name)


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


def test_请求限流_抛429(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 429, "over_request_rate_limit")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 429


def test_邮件限流_抛429而非502(monkeypatch, fake_supabase):
    # 线上真实故障回归：Supabase 端开启邮箱确认 + 内置邮件服务限流，
    # 该 code 曾落到兜底分支被错报成 502（"稍后重试"），掩盖了配置问题。
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError(
        "msg", 429, "over_email_send_rate_limit"
    )
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 429


def test_注册被关闭_抛403(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 422, "signup_disabled")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 403


def test_邮件通道未配置_抛503(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError(
        "msg", 400, "email_address_not_authorized"
    )
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 503


def test_未覆盖的AuthApi错误_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_error = AuthApiError("msg", 400, "some_unknown_code")
    with pytest.raises(HTTPException) as e:
        register_user("user@example.com", "password123")
    assert e.value.status_code == 502


def test_注册成功但未返回session_记录告警(monkeypatch, fake_supabase, caplog):
    # 「注册即激活」是本项目的设计要求：Supabase 端若仍开启邮箱确认，
    # 这里会拿到空 session —— 必须留下告警，否则前端只表现为"点了注册没反应"。
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.sign_up_result = FakeSignUpResult(
        user=SimpleNamespace(id="user-123"), session=None
    )
    with caplog.at_level(logging.WARNING):
        result = register_user("user@example.com", "password123")
    assert result["session"] is None
    assert "未返回 session" in caplog.text


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


def test_删除账号失败_降级SQL兜底成功(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.delete_user_error = RuntimeError("delete fail")
    delete_account("user-1", "user@example.com", "password123")  # 不抛异常（SQL 兜底成功）
    assert fake_supabase.rpc_calls == [
        ("purge_user_data", {"p_user_id": "user-1"}),
        ("delete_auth_user", {"p_user_id": "user-1"}),
    ]


def test_删除账号失败_且SQL兜底也失败_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.delete_user_error = RuntimeError("delete fail")
    fake_supabase.rpc_errors = {"delete_auth_user": RuntimeError("sql fail")}
    with pytest.raises(HTTPException) as e:
        delete_account("user-1", "user@example.com", "password123")
    assert e.value.status_code == 502


# ==================== refresh_session_token（免登录核心）====================


def _session(access="new-access", refresh="new-refresh"):
    return SimpleNamespace(access_token=access, refresh_token=refresh, expires_in=3600)


def test_刷新成功_返回新的token对(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_result = FakeSignUpResult(
        user=SimpleNamespace(id="user-123"), session=_session()
    )

    result = refresh_session_token("old-refresh")

    assert result["session"].access_token == "new-access"
    # 轮转：返回的 refresh_token 与传入的不同，调用方必须覆盖保存
    assert result["session"].refresh_token == "new-refresh"
    assert result["user"].id == "user-123"


def test_刷新_token原样透传给supabase(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_result = FakeSignUpResult(
        user=SimpleNamespace(id="user-123"), session=_session()
    )

    refresh_session_token("the-old-token")

    assert fake_supabase.refresh_calls == ["the-old-token"]


def test_刷新_空token_抛400且不调用supabase(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)

    with pytest.raises(HTTPException) as e:
        refresh_session_token("   ")

    assert e.value.status_code == 400
    # 应用层提前拦截，不产生任何网络调用
    assert fake_supabase.refresh_calls == []


def test_刷新_数据库未就绪_抛500(monkeypatch):
    monkeypatch.setattr(auth_service, "get_supabase", lambda: None)

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 500


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "refresh_token_not_found"),   # token 不存在
        (400, "refresh_token_already_used"),  # 旧 token 已被轮转作废（重复使用）
        (401, None),
        (403, None),
    ],
)
def test_refresh_token不可用_一律401(monkeypatch, fake_supabase, status, code):
    """失败原因不同，但对前端动作一致：清本地凭证 + 重新登录，故文案不细分。"""
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthApiError("msg", status, code)

    with pytest.raises(HTTPException) as e:
        refresh_session_token("dead-token")

    assert e.value.status_code == 401
    assert "重新登录" in e.value.detail


def test_刷新_请求限流_抛429(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthApiError("msg", 429, "over_request_rate_limit")

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 429


def test_刷新_网络类故障_抛502而非401(monkeypatch, fake_supabase, caplog):
    """网关类故障若误判成 401，会把有效用户无故踢下线。

    断言日志文案是必须的：AuthRetryableError 不是 AuthApiError 的子类
    （二者都派生自 CustomAuthError），若哪天层级变了被前面的分支吞掉，
    仅断言 502 会因「通用 Exception 兜底也是 502」而假通过。
    """
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthRetryableError("gateway", 503)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as e:
            refresh_session_token("rt")

    assert e.value.status_code == 502
    assert "网络异常" in caplog.text
    assert "未知异常" not in caplog.text  # 确认走的是 AuthRetryableError 分支，非通用兜底


@pytest.mark.parametrize(
    "status,code,expected",
    [
        # 4xx + 已知失效码：状态码不常见，但错误码明确 → 走重新登录
        (422, "refresh_token_already_used", 401),
        # 5xx：一律不判失效，避免 Supabase 抖动时把有效用户登出
        (500, "session_expired", 502),
        (503, "refresh_token_not_found", 502),
    ],
)
def test_刷新_失效判定不跨越5xx边界(monkeypatch, fake_supabase, status, code, expected):
    """_REFRESH_DEAD_CODES 分支只能在 4xx 生效。

    5xx 即便携带失效类错误码也必须按服务故障处理 —— 否则「5xx 不登出」
    这条原则会被错误码判定绕过。
    """
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthApiError("msg", status, code)

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == expected


def test_刷新_未覆盖的错误码_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthApiError("msg", 500, "some_unknown_code")

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 502


def test_刷新_未知异常_抛502(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = RuntimeError("boom")

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 502


def test_刷新_底层抛缺session异常_抛400(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_error = AuthSessionMissingError()

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 400


def test_刷新_返回空session_抛401(monkeypatch, fake_supabase):
    _patch_supabase(monkeypatch, fake_supabase)
    fake_supabase.refresh_result = FakeSignUpResult(user=None, session=None)

    with pytest.raises(HTTPException) as e:
        refresh_session_token("rt")

    assert e.value.status_code == 401


def test_刷新_日志不得泄漏refresh_token(monkeypatch, fake_supabase, caplog):
    """refresh_token 等同密码，任何日志路径都不得落盘。"""
    secret = "v1.SUPER-SECRET-REFRESH-TOKEN"
    _patch_supabase(monkeypatch, fake_supabase)
    # 构造一个 message 里带 token 的异常——若实现去记 e.message，本用例会失败
    fake_supabase.refresh_error = AuthApiError(
        f"Invalid Refresh Token: {secret}", 400, "refresh_token_not_found"
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(HTTPException):
            refresh_session_token(secret)

    assert secret not in caplog.text
