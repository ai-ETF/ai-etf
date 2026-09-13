"""market API 单元测试（quotes 子模块）。

模块名称：server/api/market/quotes.py
所测功能：spot / spot/name / ranking 端点（FinanceApiService 替身）
测试方法：FastAPI TestClient + monkeypatch FinanceApiService，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.market import router


def _spot_dict(code="512890", name="红利低波ETF"):
    return {
        "code": code, "name": name, "data_date": "2026-01-05", "update_time": "10:00:00",
        "price": 1.5, "change": 0.01, "change_pct": 0.67, "prev_close": 1.49,
        "open": 1.49, "high": 1.52, "low": 1.48, "amplitude": 2.68,
        "volume": 1000000, "amount": 1500000, "turnover_rate": 1.5, "volume_ratio": 0.8,
        "bid_price": 1.5, "ask_price": 1.51, "outer_vol": 600000, "inner_vol": 400000,
        "order_ratio": 0.2, "main_inflow": 100000, "main_inflow_pct": 6.7,
        "latest_shares": 1000000000, "float_mv": 1500000000, "total_mv": 1500000000,
        "source": "api",
    }


class FakeFinanceApiService:
    spot = _spot_dict()
    spot_by_name = _spot_dict()
    ranking = [{"code": "512890", "name": "红利低波ETF", "price": 1.5, "change": 0.01,
                "change_pct": 0.67, "turnover_rate": 1.5, "amount": 1500000}]

    def query_spot(self, fund_code):
        return self.spot

    def query_spot_by_name(self, fund_name):
        return self.spot_by_name

    def query_ranking(self, sort_by="涨跌幅", top_n=10, ascending=False):
        return self.ranking


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("server.api.market.quotes.FinanceApiService", FakeFinanceApiService)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_spot_查到行情(client):
    resp = client.get("/market/spot/512890")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["code"] == "512890"
    assert data["data"]["price"] == 1.5


def test_spot_未找到(client):
    FakeFinanceApiService.spot = None
    resp = client.get("/market/spot/999999")
    assert resp.status_code == 200
    assert "未找到基金代码" in resp.json()["error"]


def test_spot_by_name(client):
    FakeFinanceApiService.spot_by_name = _spot_dict(name="红利低波ETF")
    resp = client.get("/market/spot/name/红利低波ETF")
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "红利低波ETF"


def test_ranking(client):
    resp = client.get("/market/ranking", params={"sort_by": "涨跌幅", "top_n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "512890"
