"""market API 单元测试（search / detail 子模块）。

模块名称：server/api/market/search.py、server/api/market/detail.py

所测功能：
- `/market/search`：只返回支持目录内的基金，且返回最新净值
- `/market/detail`：目录外代码 → 404 + 明确原因；历史净值不可用 → 503

测试方法：FastAPI TestClient + monkeypatch FinanceApiService，全程不联网、不连 Supabase。

2026-10-26：spot / spot/name / ranking 端点随 30 秒行情缓存下线，其用例一并删除。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.market import router


# ==================== search ====================


class _搜索服务:
    def search_catalog(self, keyword, limit=10):
        return [{
            "code": "110020", "name": "易方达沪深300ETF联接A",
            "fund_type": "指数型-股票", "net_asset_scale": "123456789.12",
            "nav": 1.52, "nav_date": "2026-01-06",
        }]


class _空搜索服务:
    def search_catalog(self, keyword, limit=10):
        return []


@pytest.fixture
def search_client(monkeypatch):
    monkeypatch.setattr("server.api.market.search.FinanceApiService", _搜索服务)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_search_命中并返回最新净值(search_client):
    resp = search_client.get("/market/search", params={"keyword": "沪深300"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "110020"
    assert body["items"][0]["nav"] == 1.52
    assert body["items"][0]["nav_date"] == "2026-01-06"


def test_search_场内ETF代码无结果(search_client, monkeypatch):
    """场内 ETF 不在支持目录内：搜代码必须「没有任何结果」。"""
    monkeypatch.setattr("server.api.market.search.FinanceApiService", _空搜索服务)
    resp = search_client.get("/market/search", params={"keyword": "512890"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "items": []}


# ==================== detail ====================


class _抛净值不可用的服务:
    """历史还没补齐 / 上游抓不到：暂时状态，不是「没有净值」。"""

    def query_detail(self, fund_code, nav_limit=None):
        from server.services.fund_nav_service import FundNavUnavailable
        raise FundNavUnavailable(fund_code, "历史净值未就绪（history_status=pending）")

    def _resolve_fund_code(self, fund_name):
        return "110020"


class _目录外服务:
    """目录外代码（场内 ETF / 非白名单基金）必须 404，不回退上游。"""

    def query_detail(self, fund_code, nav_limit=None):
        from server.services.fund_nav_service import FundNotSupported
        raise FundNotSupported(fund_code)

    def _resolve_fund_code(self, fund_name):
        return "512890"


class _正常服务:
    def query_detail(self, fund_code, nav_limit=None):
        return {"code": fund_code, "full_name": "易方达沪深300ETF联接A",
                "is_qdii": False, "nav_history": []}

    def _resolve_fund_code(self, fund_name):
        return "110020"


@pytest.fixture
def detail_client(monkeypatch):
    monkeypatch.setattr("server.api.market.detail.FinanceApiService", _正常服务)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_detail_历史净值暂不可用返回503(detail_client, monkeypatch):
    monkeypatch.setattr("server.api.market.detail.FinanceApiService", _抛净值不可用的服务)
    resp = detail_client.get("/market/detail/110020")
    assert resp.status_code == 503
    assert "历史净值未就绪" in resp.json()["detail"]


def test_detail_按名称查询_历史净值暂不可用同样返回503(detail_client, monkeypatch):
    monkeypatch.setattr("server.api.market.detail.FinanceApiService", _抛净值不可用的服务)
    resp = detail_client.get("/market/detail/name/易方达沪深300ETF联接A")
    assert resp.status_code == 503


def test_detail_目录外代码返回404并说明原因(detail_client, monkeypatch):
    monkeypatch.setattr("server.api.market.detail.FinanceApiService", _目录外服务)
    resp = detail_client.get("/market/detail/512890")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "基金 512890 不在支持目录内"


def test_detail_按名称命中目录外基金也返回404(detail_client, monkeypatch):
    monkeypatch.setattr("server.api.market.detail.FinanceApiService", _目录外服务)
    resp = detail_client.get("/market/detail/name/红利低波ETF")
    assert resp.status_code == 404
    assert "不在支持目录内" in resp.json()["detail"]


def test_detail_正常返回时is_qdii透传(detail_client):
    resp = detail_client.get("/market/detail/110020")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_qdii"] is False
    assert body["code"] == "110020"
    assert "realtime" not in body
