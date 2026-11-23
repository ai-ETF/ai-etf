"""deps 单元测试：认证依赖注入。

模块名称：server/auth/deps.py
所测功能：extract_and_verify（Bearer 前缀解析 / 令牌无效 / 已撤销 / 成功）、
         get_current_user（从 Authorization 头取用户）
测试方法：monkeypatch verify_supabase_token / is_revoked / extract_and_verify，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import HTTPException

from server.auth import deps


# ==================== extract_and_verify ====================


def test_缺少Bearer前缀_抛401():
    with pytest.raises(HTTPException) as e:
        deps.extract_and_verify("Basic abc")
    assert e.value.status_code == 401
    assert "Bearer" in e.value.detail


def test_令牌无效_抛401(monkeypatch):
    monkeypatch.setattr(deps, "verify_supabase_token", lambda t: None)
    with pytest.raises(HTTPException) as e:
        deps.extract_and_verify("Bearer badtoken")
    assert e.value.status_code == 401


def test_令牌已撤销_抛401(monkeypatch):
    monkeypatch.setattr(deps, "verify_supabase_token", lambda t: {"sub": "u1"})
    monkeypatch.setattr(deps, "is_revoked", lambda t: True)
    with pytest.raises(HTTPException) as e:
        deps.extract_and_verify("Bearer revoked")
    assert e.value.status_code == 401
    assert "注销" in e.value.detail


def test_成功_返回token与payload(monkeypatch):
    payload = {"sub": "u1"}
    monkeypatch.setattr(deps, "verify_supabase_token", lambda t: payload)
    monkeypatch.setattr(deps, "is_revoked", lambda t: False)
    token, p = deps.extract_and_verify("Bearer goodtoken")
    assert token == "goodtoken"
    assert p is payload


# ==================== get_current_user ====================


@pytest.mark.asyncio
async def test_返回sub用户id(monkeypatch):
    monkeypatch.setattr(deps, "extract_and_verify", lambda auth: ("tok", {"sub": "user-123"}))
    assert await deps.get_current_user("Bearer tok") == "user-123"


@pytest.mark.asyncio
async def test_无sub_抛401(monkeypatch):
    monkeypatch.setattr(deps, "extract_and_verify", lambda auth: ("tok", {"role": "authenticated"}))
    with pytest.raises(HTTPException) as e:
        await deps.get_current_user("Bearer tok")
    assert e.value.status_code == 401
