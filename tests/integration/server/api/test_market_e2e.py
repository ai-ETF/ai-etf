"""P1-6 行情 API 端到端：/api/market/spot + /ranking + /detail ↔ FinanceApiService（真实 AKShare 样本回放）。

模块名称：行情查询 API 路由
所测功能：真实 AKShare 样本（录制）→ _format_spot_data 列名映射 → _spot_dict 缓存 → 路由响应的纵向切片
使用的测试方法：TestClient + 真实 app + 录制的 AKShare 样本种入类级缓存（离线回放，不出网）

样本来源：`ak.fund_etf_category_sina(symbol="ETF基金")` 的前 50 行（数据源于 2026-10-13
由东财 push2 换成新浪，样本同日重录；为保证用例取得到 588710，样本中含该只的真实行）。
"""
import pickle
import sys
import types

import pandas as pd
import pytest

pytestmark = pytest.mark.integration

SAMPLE_PATH = "tests/integration/fixtures/akshare/spot_sample.pkl"


@pytest.fixture
def spot_cache():
    """把录制的真实新浪样本 DataFrame 种入 FinanceApiService._spot_dict。"""
    from server.services.finance_api_service import FinanceApiService

    with open(SAMPLE_PATH, "rb") as f:
        df = pickle.load(f)
    FinanceApiService._rebuild_spot_dict(df)
    yield
    FinanceApiService._spot_dict = None  # 清理类级缓存


@pytest.fixture
def nav_akshare(monkeypatch):
    """离线替身 akshare，服务 /detail 的历史净值与概览，并记录净值接口的入参。

    走替身而非真实网络：集成测试有出网守卫，且「上游改版」不属于本层要断言的内容
    （真实上游由 integration_net 契约测试负责，见 docs/integration/00-集成测试规划.md §8.4）。
    """
    calls = []
    mod = types.ModuleType("akshare")

    def fund_open_fund_info_em(symbol=None, indicator=None, **kw):
        calls.append({"symbol": symbol, "indicator": indicator})
        if "累计" in (indicator or ""):
            return pd.DataFrame([{"净值日期": "2026-10-09", "累计净值": 2.0}])
        return pd.DataFrame([
            {"净值日期": "2026-10-08", "单位净值": 1.9, "日增长率": 1.0},
            {"净值日期": "2026-10-09", "单位净值": 2.0, "日增长率": 5.26},
        ])

    mod.fund_open_fund_info_em = fund_open_fund_info_em
    # 基金列表：供 /detail/name/{name} 做名称→代码解析（列序同真实 fund_name_em）
    mod.fund_name_em = lambda **kw: pd.DataFrame([{
        "基金代码": "588710", "拼音缩写": "KCZZETF", "基金简称": "科创综指ETF",
        "基金类型": "指数型-股票", "拼音全称": "kechuangzongzhiETF",
    }])
    mod.fund_overview_em = lambda **kw: pd.DataFrame([{
        "基金代码": "588710", "基金全称": "科创综指ETF", "基金简称": "科创综指ETF",
    }])
    monkeypatch.setitem(sys.modules, "akshare", mod)
    # 基金列表是类级缓存（TTL 1 小时），先清干净，避免别的用例的缓存漏进来
    from server.services.finance_api_service import FinanceApiService

    monkeypatch.setattr(FinanceApiService, "_fund_list_cache", None)
    monkeypatch.setattr(FinanceApiService, "_fund_list_cache_time", 0)
    return calls


def test_detail_净值历史与请求代码一致(api_client, nav_akshare):
    """回归守卫：历史净值必须来自被请求的那只基金（旧实现漏传 fund_code）。"""
    resp = api_client.get("/api/market/detail/588710")
    assert resp.status_code == 200

    nav = resp.json()["nav_history"]
    assert [i["date"] for i in nav] == ["2026-10-08", "2026-10-09"]
    assert nav[1]["nav"] == 2.0
    assert nav[1]["accumulated_nav"] == 2.0
    assert nav[1]["daily_growth"] == 5.26
    assert [c["symbol"] for c in nav_akshare] == ["588710", "588710"]


def test_detail_nav_limit_可收窄且校验上限(api_client, nav_akshare):
    """前端按区间切走势需要足够条数，但入参得受约束（越界 422，不得静默截断）。"""
    assert len(api_client.get("/api/market/detail/588710", params={"nav_limit": 1}).json()["nav_history"]) == 1
    assert api_client.get("/api/market/detail/588710", params={"nav_limit": 0}).status_code == 422
    assert api_client.get("/api/market/detail/588710", params={"nav_limit": 999999}).status_code == 422


def test_detail_按名称查询同样返回净值(api_client, nav_akshare):
    resp = api_client.get("/api/market/detail/name/科创综指ETF")
    assert resp.status_code == 200
    assert resp.json()["nav_history"], "按名称查询也应带出历史净值"


def test_spot_查询单只ETF_返回真实列名映射(api_client, spot_cache):
    resp = api_client.get("/api/market/spot/588710")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("data"), f"应返回行情数据，实际 error={body.get('error')}"
    data = body["data"]
    assert data["code"] == "588710"
    # 真实 AKShare 中文列名已被 _format_spot_data 映射为标准英文字段
    assert "name" in data
    assert "price" in data
    assert "change_pct" in data
    assert isinstance(data["price"], (int, float))


def test_spot_查询不存在代码_返回error(api_client, spot_cache):
    resp = api_client.get("/api/market/spot/999999")
    assert resp.status_code == 200
    assert resp.json().get("error")


def test_ranking_返回涨幅榜(api_client, spot_cache):
    resp = api_client.get("/api/market/ranking", params={"top_n": 10, "order": "desc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 0
    assert len(body["items"]) == body["total"]
    # 榜单项含行情字段
    assert "code" in body["items"][0]
    assert "change_pct" in body["items"][0]
