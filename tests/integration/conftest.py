"""集成测试 conftest：真实 Supabase 连接、库目标断言、出网守卫。

设计原则（见 docs/integration/00-集成测试规划.md）：
- 只连**本地 Supabase 栈**（http://127.0.0.1:54321），绝不允许连生产库；
- 出网守卫：拦截一切非 localhost 的 socket 连接，防止漏网的测试偷偷打真实
  AKShare / LLM / 生产库；
- 清理采用「合成 UUID + 定向清理」，清理失败必须抛错（见 _utils/db.py）。
"""
import os
import socket
import subprocess

import pytest


# ---------- 本地库配置解析 ----------

def _resolve_local_supabase() -> tuple[str, str]:
    """返回 (URL, service_role_key)。

    优先级：环境变量 TEST_SUPABASE_URL / TEST_SUPABASE_SERVICE_ROLE_KEY（CI 场景）
    → `supabase status -o env`（本地 CLI 动态获取）。

    `supabase status` 需要 docker socket 权限；当前会话可能不在 docker 组
    （用户已在组内但未重开终端），故用 `sg docker -c` 包裹兜底。
    """
    url = os.getenv("TEST_SUPABASE_URL")
    key = os.getenv("TEST_SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return url, key

    out = ""
    candidates = [
        ["sg", "docker", "-c", "supabase status -o env"],
        ["supabase", "status", "-o", "env"],
    ]
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and "SERVICE_ROLE_KEY" in proc.stdout:
            out = proc.stdout
            break

    env = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

    url = env.get("API_URL") or env.get("SUPABASE_URL") or "http://127.0.0.1:54321"
    key = env.get("SERVICE_ROLE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY")
    return url, key


def _assert_local_target(url: str) -> None:
    """库目标断言：只允许连本地栈，误连生产直接退出整个测试会话。"""
    if not url:
        pytest.exit("集成测试缺少 Supabase URL（本地栈未启动或 TEST_SUPABASE_URL 未设置）", returncode=3)
    if "127.0.0.1" not in url and "localhost" not in url:
        pytest.exit(
            f"拒绝连接非本地 Supabase（{url}）——集成测试只允许连本地栈，防止误写生产库",
            returncode=3,
        )


# ---------- 出网守卫 ----------

@pytest.fixture(autouse=True)
def _block_outbound_network(monkeypatch):
    """禁止测试进程连接非 localhost 地址，白名单本地回环。"""
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    real_create_connection = socket.create_connection

    def guarded(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in allowed_hosts:
            raise RuntimeError(
                f"集成测试禁止出网：{host}。外部 API（AKShare/LLM）须用录制回放或假对象隔离。"
            )
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)
    yield


# ---------- 客户端 fixture ----------

@pytest.fixture(scope="session")
def supabase_client():
    """连接本地 Supabase 栈的 service_role 客户端（会话级复用）。"""
    from supabase import create_client

    url, key = _resolve_local_supabase()
    _assert_local_target(url)
    if not key:
        pytest.exit("集成测试缺少 Supabase service_role key", returncode=3)

    client = create_client(url, key)
    # 冒烟校验：能连通且能查 schema（空表也可）
    try:
        client.table("fund_fee_rules").select("count", count="exact").limit(0).execute()
    except Exception as e:  # noqa: BLE001
        pytest.exit(f"无法连接本地 Supabase（{url}）：{e}", returncode=3)
    return client


# ---------- 服务 fixture：注入本地库 client（绕过 get_supabase 读生产 env） ----------

@pytest.fixture
def fee_service(supabase_client):
    """FundFeeService 实例，client 指向本地库（含 21 条种子费率规则）。"""
    from server.services.fund_fee_service import FundFeeService

    svc = FundFeeService()
    svc._client = supabase_client
    return svc


@pytest.fixture
def watchlist_service(supabase_client):
    """WatchlistService 实例，client 指向本地库。"""
    from server.services.watchlist_service import WatchlistService

    svc = WatchlistService()
    svc._client = supabase_client
    return svc


@pytest.fixture
def risk_service(supabase_client):
    """RiskService 实例，client 指向本地库（含种子问卷）。"""
    from server.services.risk_service import RiskService

    svc = RiskService()
    svc._client = supabase_client
    return svc


@pytest.fixture
def user_id(supabase_client):
    """合成 user_id，用于**无 FK 到 auth.users** 的表（accounts/watchlist/positions 等）。

    测试结束后调用 purge_user_data RPC 定向清理该用户的全部业务数据；
    清理失败会抛错，不做静默吞掉。
    """
    import uuid as _uuid

    uid = str(_uuid.uuid4())
    yield uid
    supabase_client.rpc("purge_user_data", {"p_user_id": uid}).execute()


@pytest.fixture
def auth_user_id(supabase_client):
    """真实 auth 用户（admin.create_user），用于**有 FK 到 auth.users** 的表
    （chats/messages/documents/user_risk_answers/user_risk_profiles 等）。

    清理顺序：先 purge 业务数据（含 FK 引用），再删 auth 用户本身。
    """
    import uuid as _uuid

    email = f"test-{_uuid.uuid4()}@example.com"
    resp = supabase_client.auth.admin.create_user(
        {"email": email, "password": "test-password-123", "email_confirm": True}
    )
    uid = resp.user.id
    yield uid
    supabase_client.rpc("purge_user_data", {"p_user_id": uid}).execute()
    supabase_client.auth.admin.delete_user(uid)
