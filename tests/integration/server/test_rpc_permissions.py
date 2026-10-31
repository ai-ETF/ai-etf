"""高危 RPC 权限回归：purge_user_data / delete_auth_user 只允许 service_role 调用。

模块名称：PostgREST RPC ↔ Postgres 函数权限（supabase/migrations/20261031120000_revoke_privileged_rpc_execute.sql）
所测功能：匿名用户、普通登录用户调用注销相关 RPC 必须被拒绝；service_role 仍可调用
使用的测试方法：真实本地 Supabase 栈 + 真实 HTTP 调用 + 不存在的合成 UUID（不触碰任何数据）
"""
import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration

# 这两个函数会清空用户全部业务数据 / 直接删除账号，绝不能对前端可拿到的密钥开放
DANGEROUS_RPCS = ["purge_user_data", "delete_auth_user"]


def _call_rpc(stack: dict, fn: str, token: str) -> httpx.Response:
    """以给定 JWT 调用 RPC；p_user_id 用随机 UUID，保证不删除真实数据。"""
    return httpx.post(
        f"{stack['url']}/rest/v1/rpc/{fn}",
        json={"p_user_id": str(uuid.uuid4())},
        headers={"apikey": token, "Authorization": f"Bearer {token}"},
        timeout=10,
    )


@pytest.mark.parametrize("fn", DANGEROUS_RPCS)
def test_匿名用户不能调用高危RPC(fn, local_stack):
    """anon key 会随前端下发，拿到它的人不能清库/删号。"""
    assert local_stack["anon_key"], "取不到本地栈 anon key，无法验证匿名权限"
    resp = _call_rpc(local_stack, fn, local_stack["anon_key"])
    assert resp.status_code in (401, 403), resp.text
    assert "permission denied" in resp.text


@pytest.mark.parametrize("fn", DANGEROUS_RPCS)
def test_普通登录用户不能调用高危RPC(fn, local_stack, auth_headers):
    """已登录用户只能操作自己的数据，不能借 RPC 删别人。"""
    headers = auth_headers(str(uuid.uuid4()))
    token = headers["Authorization"].removeprefix("Bearer ")
    resp = _call_rpc(local_stack, fn, token)
    assert resp.status_code in (401, 403), resp.text
    assert "permission denied" in resp.text


@pytest.mark.parametrize("fn", DANGEROUS_RPCS)
def test_service_role仍可调用高危RPC(fn, local_stack):
    """后端注销流程依赖这两个函数，收紧权限后必须仍然可用。"""
    resp = _call_rpc(local_stack, fn, local_stack["service_key"])
    assert resp.status_code == 204, resp.text
