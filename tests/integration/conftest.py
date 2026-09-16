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
import sys
import types

import pytest


# ---------- 重依赖替身（import server.app 前预填充 sys.modules） ----------
# langchain_anthropic 导入 >60s；document_service → rag.embedder/graphs → torch/langgraph 极重。
# 二者在 import server.app（→ api → secure_chat/upload）时被连带加载，拖垮所有 API 测试。
# 阶段 2 的 API 端到端不测 upload，故 document_service 用空替身；server.llm 的 langchain
# 类仅作类型提示、运行时惰性，空替身即可让真实代码加载。


def _install(name, **attrs):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_install("langchain_anthropic", ChatAnthropic=type("ChatAnthropic", (), {}))
_install("langchain_core")
_install("langchain_core.language_models")
_install("langchain_core.language_models.chat_models", BaseChatModel=type("BaseChatModel", (), {}))
_install("langchain_core.messages", BaseMessage=type("BaseMessage", (), {}))
_install("server.services.document_service", DocumentService=type("DocumentService", (), {}))


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
    """禁止测试进程连接非 localhost 地址，白名单本地回环。

    在 socket.socket.connect 这一最底层拦截，覆盖 requests/httpx/urllib/akshare
    等所有 HTTP 客户端（它们最终都落到 socket.connect）。
    """
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in allowed_hosts:
            raise RuntimeError(
                f"集成测试禁止出网：{host}。外部 API（AKShare/LLM）须用录制回放或假对象隔离。"
            )
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
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
def portfolio_service(supabase_client, monkeypatch):
    """PortfolioService 实例。

    关键：PortfolioService 内部会自行实例化 FundFeeService/RiskService，
    二者经 `get_supabase()` 读 env 会连生产库。此处 monkeypatch `get_supabase`
    返回本地库 client，使整个调用链（含内部服务）都落在本地库上。
    """
    from server.storage import supabase_client as sc

    monkeypatch.setattr(sc, "get_supabase", lambda: supabase_client)

    from server.services.portfolio_service import PortfolioService

    return PortfolioService()


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


# ---------- JWT 自签 + API 端到端 fixture ----------

def _resolve_local_jwt_secret() -> str:
    """本地 Supabase 的 JWT secret（supabase status 输出），默认 supabase 公开默认值。"""
    for cmd in [
        ["sg", "docker", "-c", "supabase status -o env"],
        ["supabase", "status", "-o", "env"],
    ]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("JWT_SECRET="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "super-secret-jwt-token-with-at-least-32-characters-long"


def mint_token(user_id: str, secret: str) -> str:
    """自签 HS256 JWT（aud=authenticated），覆盖所有 Depends(get_current_user) 路由。"""
    import jwt

    return jwt.encode(
        {"sub": user_id, "role": "authenticated", "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )


@pytest.fixture
def jwt_secret():
    """本地 Supabase 的 JWT secret。"""
    return _resolve_local_jwt_secret()


@pytest.fixture
def auth_headers(jwt_secret):
    """返回函数：根据 user_id 生成 Authorization headers（自签 JWT）。"""

    def _make(user_id: str) -> dict:
        return {"Authorization": f"Bearer {mint_token(user_id, jwt_secret)}"}

    return _make


@pytest.fixture
def sql_delete_auth_user():
    """返回函数：SQL 直删 auth 用户（先删 identities 再删 users）。

    sign_up 创建的用户，`auth.admin.delete_user` 会报「User not allowed」
    （create_user 创建的用户则能删），故 register 测试的清理需走 SQL 直删。
    """

    def _delete(user_id: str) -> None:
        import time

        sql = (
            f"DELETE FROM auth.identities WHERE user_id = '{user_id}';"
            f"DELETE FROM auth.users WHERE id = '{user_id}';"
        )
        cmd = ["sg", "docker", "-c",
               f"docker exec supabase_db_ai-etf psql -U postgres -d postgres -c \"{sql}\""]
        # docker exec 偶发失败（资源竞争/超时），重试 3 次提升健壮性
        last_err = None
        for _ in range(3):
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                last_err = e
                time.sleep(1)
        raise last_err

    return _delete


@pytest.fixture
def api_client(monkeypatch):
    """FastAPI TestClient：真实 app + 独立本地库 client + 本地 JWT secret。

    - get_supabase 指向一个**独立**的 service_role client（每个测试新建），
      而非共享的 supabase_client——因为 secure_chat 的 sign_up 会自动设置 client
      的 session（auto-login），把 service_role 切成 authenticated role 触发 RLS，
      独立 client 可隔离这种污染；
    - 调度器替身，避免 lifespan 启动 30s 行情刷新任务打 AKShare；
    - SETTINGS.SUPABASE_JWT_SECRET 指向本地，使自签 token 能通过 verify。
    """
    from supabase import create_client

    url, key = _resolve_local_supabase()
    _assert_local_target(url)
    local_client = create_client(url, key)

    from server.storage import supabase_client as sc

    monkeypatch.setattr(sc, "get_supabase", lambda: local_client)

    monkeypatch.setattr("server.services.spot_cache_scheduler.start_scheduler", lambda: None)
    monkeypatch.setattr("server.services.spot_cache_scheduler.shutdown_scheduler", lambda: None)

    from server.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "SUPABASE_JWT_SECRET", _resolve_local_jwt_secret())

    from server.app import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client
