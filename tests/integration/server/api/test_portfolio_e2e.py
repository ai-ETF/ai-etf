"""P1-5 API 端到端：/api/portfolio/* 路由 ↔ 服务层 ↔ 真实 Postgres。

模块名称：场外基金交易 API 路由
所测功能：JWT 鉴权 → apply-purchase → 真实冻结资金 + pending 订单 + 账户/持仓查询
使用的测试方法：TestClient + 真实 app + 本地 Supabase + 合成 user_id + 冻结时钟（工作日盘中）
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

BEIJING = timezone(timedelta(hours=8))
SUBMIT_DAY = datetime(2026, 9, 14, 14, 0, tzinfo=BEIJING)


def test_申购_冻结资金并写pending订单(api_client, supabase_client, auth_headers, user_id):
    import time_machine

    with time_machine.travel(SUBMIT_DAY):
        resp = api_client.post(
            "/api/portfolio/apply-purchase",
            json={"fund_code": "110020", "amount": 1000, "price": 1.5},
            headers=auth_headers(user_id),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "pending"

    # 真实落库：冻结 1000，现金 99000
    acct = supabase_client.table("accounts").select("*").eq("user_id", user_id).execute().data[0]
    assert Decimal(str(acct["cash"])) == Decimal("99000")
    assert Decimal(str(acct["frozen_cash"])) == Decimal("1000")

    # pending 订单
    orders = supabase_client.table("trade_orders").select("*").eq("user_id", user_id).execute().data
    assert len(orders) == 1
    assert orders[0]["status"] == "pending"


def test_账户概况_反映冻结(api_client, auth_headers, user_id):
    import time_machine

    with time_machine.travel(SUBMIT_DAY):
        api_client.post(
            "/api/portfolio/apply-purchase",
            json={"fund_code": "110020", "amount": 1000, "price": 1.5},
            headers=auth_headers(user_id),
        )

    resp = api_client.get("/api/portfolio/account", headers=auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(str(body["cash"])) == Decimal("99000")
    assert Decimal(str(body["frozen_cash"])) == Decimal("1000")


def test_申购不支持基金_返回400(api_client, auth_headers, user_id):
    resp = api_client.post(
        "/api/portfolio/apply-purchase",
        json={"fund_code": "999999", "amount": 1000, "price": 1.0},
        headers=auth_headers(user_id),
    )
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]
