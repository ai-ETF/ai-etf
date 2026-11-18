"""portfolio API 单元测试。

模块名称：server/api/portfolio.py
所测功能：apply-purchase / apply-redeem / positions / account / trade-flow / auto-invest 端点
测试方法：FastAPI TestClient + dependency_overrides 注入固定 user_id + monkeypatch PortfolioService，全程不联网、不连 Supabase。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth.deps import get_current_user
from server.api.portfolio import router


class FakePortfolioService:
    purchase_result = {"success": True, "message": "申购申请已提交", "data": None, "risk_warning": None}
    redeem_result = {"success": True, "message": "赎回申请已提交", "data": None}
    positions_result = {"total": 0, "items": [], "total_pnl": 0, "total_position_value": 0}
    account_result = {"cash": 100000.0, "frozen_cash": 0, "position_value": 0,
                      "total_assets": 100000.0, "total_pnl": 0, "total_return_rate": 0, "position_count": 0}
    trade_flow_result = {"total": 0, "page": 1, "page_size": 20, "total_pages": 0, "items": []}
    auto_invest_config = {"enabled": True, "reserve": 0.0, "money_fund_code": "000198",
                          "money_fund_name": "天弘余额宝货币市场基金"}

    last_purchase_kwargs = {}
    last_redeem_kwargs = {}
    confirm_result = {"status": "ok", "scanned": 0, "processed": 0, "skipped": 0}

    def apply_purchase(self, user_id, fund_code, amount, price=None, client_order_id=None):
        FakePortfolioService.last_purchase_kwargs = {"client_order_id": client_order_id}
        return self.purchase_result

    def apply_redeem(self, user_id, fund_code, quantity, price=None, client_order_id=None):
        FakePortfolioService.last_redeem_kwargs = {"client_order_id": client_order_id}
        return self.redeem_result

    def confirm_pending_orders(self):
        return self.confirm_result

    def list_positions(self, user_id, include_quote=True):
        return self.positions_result

    def account_summary(self, user_id):
        return self.account_result

    def query_trade_flow(self, user_id, fund_code=None, direction=None, page=1, page_size=20):
        return self.trade_flow_result

    def get_auto_invest_config(self, user_id):
        return self.auto_invest_config

    def set_auto_invest_config(self, user_id, enabled, reserve):
        return self.auto_invest_config


@pytest.fixture
def client(monkeypatch):
    # 多数端点用模块级 import；auto-invest 端点在函数内重新 import，两处都要替身
    monkeypatch.setattr("server.api.portfolio.PortfolioService", FakePortfolioService)
    monkeypatch.setattr("server.services.portfolio_service.PortfolioService", FakePortfolioService)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


def test_apply_purchase_成功(client):
    FakePortfolioService.purchase_result = {
        "success": True, "message": "申购申请已提交",
        "data": {"fund_code": "110020", "fund_name": "易方达", "amount": 1000.0, "fee": 1.5,
                 "price": 1.5, "status": "pending"},
        "risk_warning": None,
    }
    resp = client.post("/portfolio/apply-purchase", json={"fund_code": "110020", "amount": 1000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["fund_code"] == "110020"


def test_apply_purchase_失败返回400(client):
    FakePortfolioService.purchase_result = {"success": False, "message": "暂不支持基金 999999 的交易", "data": None}
    resp = client.post("/portfolio/apply-purchase", json={"fund_code": "999999", "amount": 1000})
    assert resp.status_code == 400


def test_apply_purchase_Idempotency_Key透传(client):
    FakePortfolioService.purchase_result = {"success": True, "message": "ok", "data": None, "risk_warning": None}
    resp = client.post("/portfolio/apply-purchase",
                       json={"fund_code": "110020", "amount": 1000},
                       headers={"Idempotency-Key": "ck-1"})
    assert resp.status_code == 200
    assert FakePortfolioService.last_purchase_kwargs["client_order_id"] == "ck-1"


def test_apply_redeem_Idempotency_Key透传(client):
    FakePortfolioService.redeem_result = {"success": True, "message": "ok", "data": None}
    resp = client.post("/portfolio/apply-redeem",
                       json={"fund_code": "110020", "quantity": 100},
                       headers={"Idempotency-Key": "rk-1"})
    assert resp.status_code == 200
    assert FakePortfolioService.last_redeem_kwargs["client_order_id"] == "rk-1"


def test_apply_redeem_成功(client):
    FakePortfolioService.redeem_result = {
        "success": True, "message": "赎回申请已提交",
        "data": {"fund_code": "110020", "fund_name": "易方达", "amount": 0.0, "fee": 0.0,
                 "price": 0.0, "quantity": 100.0, "status": "pending"},
    }
    resp = client.post("/portfolio/apply-redeem", json={"fund_code": "110020", "quantity": 100})
    assert resp.status_code == 200
    assert resp.json()["data"]["quantity"] == 100.0


def test_positions(client):
    FakePortfolioService.positions_result = {
        "total": 1, "items": [{
            "id": "p1", "user_id": "u1", "fund_code": "110020", "fund_name": "易方达",
            "quantity": 100.0, "cost_price": 1.5, "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }],
        "total_pnl": 0, "total_position_value": 150.0,
    }
    resp = client.get("/portfolio/positions")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_account(client):
    resp = client.get("/portfolio/account")
    assert resp.status_code == 200
    assert resp.json()["total_assets"] == 100000.0


def test_trade_flow(client):
    resp = client.get("/portfolio/trade-flow", params={"page": 1, "page_size": 20})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_get_auto_invest_config(client):
    resp = client.get("/portfolio/auto-invest/config")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_set_auto_invest_config(client):
    resp = client.post("/portfolio/auto-invest/config", json={"enabled": False, "reserve": 5000})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


# ==================== /confirm-pending：管理员鉴权 + 批次响应 ====================


def test_confirm_pending_未配置管理员凭证返回503(client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    resp = client.post("/portfolio/confirm-pending")
    assert resp.status_code == 503


def test_confirm_pending_凭证错误返回401(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")
    resp = client.post("/portfolio/confirm-pending", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_confirm_pending_凭证正确返回批次字段(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")
    FakePortfolioService.confirm_result = {
        "run_id": "r1", "status": "ok", "scanned": 3, "confirmed": 2, "rejected": 0,
        "skipped_nav": 1, "retryable": 0, "manual_review": 0, "settled": 0,
        "processed": 3, "skipped": 1, "duration_ms": 12,
    }
    resp = client.post("/portfolio/confirm-pending", headers={"X-Admin-Token": "s3cret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "r1" and body["scanned"] == 3
    assert body["processed"] == 3 and body["skipped"] == 1


def test_confirm_pending_busy仍返回200(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "s3cret")
    FakePortfolioService.confirm_result = {"status": "busy", "message": "已有批次在跑"}
    resp = client.post("/portfolio/confirm-pending", headers={"X-Admin-Token": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "busy"
