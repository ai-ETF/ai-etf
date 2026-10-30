"""管理接口：交易日历刷新 / 状态核验。

模块名称：server/api/admin.py
所测功能：鉴权（503/401）、幂等键（400）、刷新错误映射（409/422/502/504）与响应契约
测试方法：TestClient + 假缓存；不联网、不连 Supabase。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import server.api.admin as admin_api
from server.app import app
from server.services.trading_calendar_cache import (
    CalendarDataInvalid,
    CalendarRefreshTimeout,
    RefreshInProgress,
    RefreshResult,
)
from server.sources.models import AllSourcesFailed

client = TestClient(app)

_REFRESH_URL = "/api/admin/trading-calendar/refresh"
_STATUS_URL = "/api/admin/trading-calendar/status"


class _FakeCache:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.dry_run_calls = []

    def refresh(self, dry_run=False):
        self.dry_run_calls.append(dry_run)
        if self.error:
            raise self.error
        return self.result

    def describe(self):
        return {"ready": True, "snapshot": None, "state": None, "rows": None}


def _result(dry_run=False):
    return RefreshResult(
        coverage_start=date(1990, 12, 19),
        coverage_end=date(2026, 12, 31),
        source="sina_trade_date",
        dry_run=dry_run,
        stats={"inserted": 1, "updated": 0, "unchanged": 100, "deleted": 0},
        diff=[],
        diff_truncated=False,
        elapsed_ms=12,
    )


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")
    return {"X-Admin-Token": "s3cret", "Idempotency-Key": "test-key"}


@pytest.fixture
def fake_cache(monkeypatch):
    cache = _FakeCache(result=_result())
    monkeypatch.setattr(admin_api, "get_calendar_cache", lambda: cache)
    return cache


def test_未配置管理凭证_返回503(monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    response = client.get(_STATUS_URL)
    assert response.status_code == 503


def test_凭证错误_返回401(token):
    response = client.get(_STATUS_URL, headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_缺少幂等键_返回400(token):
    response = client.post(_REFRESH_URL, headers={"X-Admin-Token": "s3cret"})
    assert response.status_code == 400


def test_刷新成功_返回契约字段(token, fake_cache):
    response = client.post(_REFRESH_URL, headers=token)
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["coverage_start"] == "1990-12-19"
    assert body["coverage_end"] == "2026-12-31"
    assert body["source"] == "sina_trade_date"
    assert set(body["stats"]) == {"inserted", "updated", "unchanged", "deleted"}
    assert body["idempotency_key"] == "test-key"
    assert body["request_id"]
    assert body["diff"] == []
    assert body["diff_truncated"] is False
    assert body["elapsed_ms"] == 12
    assert fake_cache.dry_run_calls == [False]


def test_dry_run_透传且不写库(token, fake_cache):
    response = client.post(_REFRESH_URL + "?dry_run=true", headers=token)
    assert response.status_code == 200
    assert fake_cache.dry_run_calls == [True]


def test_已有刷新在跑_返回409(token, fake_cache):
    fake_cache.error = RefreshInProgress("已有刷新正在执行")
    assert client.post(_REFRESH_URL, headers=token).status_code == 409


def test_数据校验失败_返回422(token, fake_cache):
    fake_cache.error = CalendarDataInvalid("交易日数量异常")
    assert client.post(_REFRESH_URL, headers=token).status_code == 422


def test_源失败_返回502(token, fake_cache):
    fake_cache.error = AllSourcesFailed(
        "calendar",
        [{"source": "sina_trade_date", "kind": "EMPTY_PAYLOAD", "error": "空"}],
    )
    response = client.post(_REFRESH_URL, headers=token)
    assert response.status_code == 502
    assert response.json()["detail"]["tried"][0]["source"] == "sina_trade_date"


def test_源超时_返回504(token, fake_cache):
    fake_cache.error = AllSourcesFailed(
        "calendar",
        [{"source": "sina_trade_date", "kind": "TIMEOUT", "error": "超时"}],
    )
    assert client.post(_REFRESH_URL, headers=token).status_code == 504


def test_整体超时_返回504(token, fake_cache):
    fake_cache.error = CalendarRefreshTimeout("超过 30s")
    assert client.post(_REFRESH_URL, headers=token).status_code == 504


def test_未预期异常_返回500(token, fake_cache):
    fake_cache.error = RuntimeError("boom")
    response = client.post(_REFRESH_URL, headers=token)
    assert response.status_code == 500
    assert "RuntimeError" in response.json()["detail"]


def test_状态接口_只读返回ready(token, fake_cache):
    response = client.get(_STATUS_URL, headers={"X-Admin-Token": "s3cret"})
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert "request_id" in response.json()
