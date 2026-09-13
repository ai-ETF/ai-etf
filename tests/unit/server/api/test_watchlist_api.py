"""watchlist API 单元测试。

模块名称：server/api/watchlist.py
所测功能：add / remove / list / clear 端点（JWT 依赖替身 + WatchlistService 替身）
测试方法：FastAPI TestClient + dependency_overrides 注入固定 user_id + monkeypatch 服务，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.deps import get_current_user
from server.api.watchlist import router


class FakeWatchlistService:
    add_result = {"success": True, "message": "添加成功", "item": None}
    remove_result = {"success": True, "message": "移除成功"}
    list_result = {"total": 0, "items": []}
    clear_result = {"success": True, "message": "已清空 0 个自选股", "removed_count": 0}

    def add(self, user_id, fund_code, fund_name=None):
        return self.add_result

    def remove(self, user_id, fund_code):
        return self.remove_result

    def list(self, user_id, include_quote=True):
        return self.list_result

    def clear(self, user_id):
        return self.clear_result


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("server.api.watchlist.WatchlistService", FakeWatchlistService)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


def test_add_自选股(client):
    FakeWatchlistService.add_result = {
        "success": True,
        "message": "添加成功",
        "item": {
            "id": "w1", "user_id": "u1", "fund_code": "512890",
            "fund_name": "红利低波ETF", "sort_order": 0, "created_at": "2026-01-01T00:00:00",
        },
    }
    resp = client.post("/watchlist/add", json={"fund_code": "512890"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["item"]["fund_code"] == "512890"


def test_remove_自选股(client):
    # TestClient.delete 不支持 body，用 request("DELETE", json=...) 发送请求体
    resp = client.request("DELETE", "/watchlist/remove", json={"fund_code": "512890"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_list_自选股(client):
    FakeWatchlistService.list_result = {
        "total": 1,
        "items": [{
            "id": "w1", "user_id": "u1", "fund_code": "512890",
            "fund_name": "红利低波ETF", "sort_order": 0, "created_at": "2026-01-01T00:00:00",
        }],
    }
    resp = client.get("/watchlist/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["fund_code"] == "512890"


def test_clear_自选股(client):
    FakeWatchlistService.clear_result = {"success": True, "message": "已清空 2 个自选股", "removed_count": 2}
    resp = client.delete("/watchlist/clear")
    assert resp.status_code == 200
    assert resp.json()["removed_count"] == 2
