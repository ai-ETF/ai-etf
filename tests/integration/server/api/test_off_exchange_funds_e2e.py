"""P1-6 API 端到端：/api/portfolio/funds* 路由 ↔ 服务层 ↔ 真实 Postgres。

模块名称：场外基金目录 API
所测功能：JWT 鉴权 → 基金列表/关键词搜索/分页 → 基金详情（含费率分档 + 风险画像）
使用的测试方法：TestClient + 真实 app + 本地 Supabase + 合成 user_id，
              数据来自 21 条真实种子费率规则（不联网）
"""
import pytest

pytestmark = pytest.mark.integration


# ==================== 鉴权 ====================


def test_无token访问基金列表_拒绝(api_client):
    resp = api_client.get("/api/portfolio/funds")
    assert resp.status_code in (401, 403)


def test_无token访问基金详情_拒绝(api_client):
    resp = api_client.get("/api/portfolio/funds/110020")
    assert resp.status_code in (401, 403)


# ==================== 列表与搜索 ====================


def test_基金列表_返回白名单基金(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds", headers=auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 20
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 20

    item = next(i for i in body["items"] if i["fund_code"] == "110020")
    assert item["fund_name"] == "易方达沪深300ETF联接A"
    assert item["fund_type"] == "of"
    assert item["share_class"] == "A"
    assert item["confirm_delay"] == 1
    assert item["redeem_settle_delay"] == 3
    assert item["risk_level"] == "moderate"
    assert item["risk_label"] == "中等风险"


def test_基金列表_列表项不含费率分档(api_client, auth_headers, user_id):
    """分档明细体积大，只在详情接口返回，列表接口不应带出。"""
    resp = api_client.get("/api/portfolio/funds", headers=auth_headers(user_id))
    assert all("purchase_fee_tiers" not in i for i in resp.json()["items"])


def test_按基金代码搜索(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds",
                          params={"keyword": "110020"}, headers=auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["fund_code"] == "110020"


def test_按基金名称搜索(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds",
                          params={"keyword": "银行"}, headers=auth_headers(user_id))
    body = resp.json()
    assert body["total"] == 2
    assert {i["fund_code"] for i in body["items"]} == {"001594", "001595"}
    assert all("银行" in i["fund_name"] for i in body["items"])


def test_搜索无结果_返回空列表(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds",
                          params={"keyword": "不存在的基金"}, headers=auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    assert resp.json()["items"] == []


def test_搜索关键词含特殊字符_不破坏查询(api_client, auth_headers, user_id):
    """PostgREST 的 or_ 过滤器用逗号/括号分隔表达式，关键词里的这些字符必须被剔除。"""
    resp = api_client.get("/api/portfolio/funds",
                          params={"keyword": "110020,name.ilike.x"}, headers=auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_分页(api_client, auth_headers, user_id):
    first = api_client.get("/api/portfolio/funds",
                           params={"page": 1, "page_size": 5}, headers=auth_headers(user_id)).json()
    second = api_client.get("/api/portfolio/funds",
                            params={"page": 2, "page_size": 5}, headers=auth_headers(user_id)).json()

    assert len(first["items"]) == 5
    assert len(second["items"]) == 5
    assert first["total"] == second["total"]
    # 两页不重叠
    assert not {i["fund_code"] for i in first["items"]} & {i["fund_code"] for i in second["items"]}


def test_每页条数超上限_被拒绝(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds",
                          params={"page_size": 500}, headers=auth_headers(user_id))
    assert resp.status_code == 422


# ==================== 详情 ====================


def test_基金详情_含费率分档与风险(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds/110020", headers=auth_headers(user_id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["fund_name"] == "易方达沪深300ETF联接A"
    assert body["min_purchase_amount"] == 10.0
    assert body["commission_rate"] == 0.0003
    assert body["purchase_fee_tiers"] == [
        {"rate": 0.0012, "amount": 1000000},
        {"rate": 0.0008, "amount": 5000000},
        {"rate": 0.0002, "amount": 10000000},
        {"rate": 0, "fixed_fee": 1000},
    ]
    assert body["redemption_fee_tiers"] == [
        {"days": 7, "rate": 0.015},
        {"days": 365, "rate": 0.005},
        {"days": 730, "rate": 0.0025},
        {"days": 730, "rate": 0.0, "inclusive": True},
    ]
    assert body["risk_level"] == "moderate"
    assert body["breadth_score"] == 1


def test_基金详情_QDII基金T加2七日(api_client, auth_headers, user_id):
    body = api_client.get("/api/portfolio/funds/000071",
                          headers=auth_headers(user_id)).json()
    assert body["confirm_delay"] == 2
    assert body["redeem_settle_delay"] == 7
    assert body["market_score"] == 3


def test_基金详情_不在白名单返回404(api_client, auth_headers, user_id):
    resp = api_client.get("/api/portfolio/funds/999999", headers=auth_headers(user_id))
    assert resp.status_code == 404
    assert "不支持" in resp.json()["detail"]


def test_基金详情_与交易白名单口径一致(api_client, auth_headers, user_id):
    """详情能查到 ⇔ 能下单；查不到 ⇔ 下单被拒。避免两处口径漂移。"""
    detail = api_client.get("/api/portfolio/funds/110020", headers=auth_headers(user_id))
    assert detail.status_code == 200

    order = api_client.post(
        "/api/portfolio/apply-purchase",
        json={"fund_code": "110020", "amount": 1000, "price": 1.5},
        headers=auth_headers(user_id),
    )
    assert order.status_code == 200

    missing = "999999"
    assert api_client.get(f"/api/portfolio/funds/{missing}",
                          headers=auth_headers(user_id)).status_code == 404
    assert api_client.post(
        "/api/portfolio/apply-purchase",
        json={"fund_code": missing, "amount": 1000, "price": 1.0},
        headers=auth_headers(user_id),
    ).status_code == 400
