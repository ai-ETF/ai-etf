"""客户端隔离语义测试。

背景：supabase-py 在执行 sign_in / sign_up / refresh_session 后会改写客户端
的 Authorization 头，并重建底层 postgrest 客户端。因此：
- 数据客户端（get_supabase）进程内复用，且必须始终保持 service_role 身份；
- 登录类操作走 get_auth_client()，每次新建、不缓存，用完即弃。

若两者共用同一个实例，任何一次登录都会让全进程后续请求以该用户身份访问
数据库（丢失 service_role、RLS 生效、跨用户串数据）。
"""
import server.storage.supabase_client as sc


def _set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
    # 重置模块单例，避免用例间互相影响；monkeypatch 会在结束时还原
    monkeypatch.setattr(sc, "_client", None)


def test_数据客户端复用_认证客户端每次新建(monkeypatch):
    _set_env(monkeypatch)
    created = []

    def fake_create(url, key):
        client = object()
        created.append((url, key, client))
        return client

    monkeypatch.setattr(sc, "create_client", fake_create)

    data1 = sc.get_supabase()
    data2 = sc.get_supabase()
    assert data1 is data2, "数据客户端应进程内复用"

    auth1 = sc.get_auth_client()
    auth2 = sc.get_auth_client()
    assert auth1 is not auth2, "登录客户端每次都应新建，避免登录态互相污染"
    assert auth1 is not data1 and auth2 is not data1, "登录客户端不能是共享的数据客户端"

    assert len(created) == 3, "两次数据客户端只建连一次，两次认证客户端各建一次"
    assert all(url == "http://127.0.0.1:54321" for url, _, _ in created)


def test_数据客户端创建失败不缓存_下次重试(monkeypatch):
    _set_env(monkeypatch)
    calls = []

    def flaky_create(url, key):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("首次建连失败")
        return "client-ok"

    monkeypatch.setattr(sc, "create_client", flaky_create)

    assert sc.get_supabase() is None
    assert sc.get_supabase() == "client-ok"


def test_认证客户端创建失败返回None(monkeypatch):
    _set_env(monkeypatch)

    def boom(url, key):
        raise RuntimeError("boom")

    monkeypatch.setattr(sc, "create_client", boom)
    assert sc.get_auth_client() is None


def test_缺少环境变量_两个入口都返回None(monkeypatch):
    monkeypatch.setattr(sc, "_client", None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)

    assert sc.get_supabase() is None
    assert sc.get_auth_client() is None
