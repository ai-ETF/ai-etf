"""P1-6 行情 API 端到端：/api/market/spot + /ranking ↔ FinanceApiService（真实 AKShare 样本回放）。

模块名称：行情查询 API 路由
所测功能：真实 AKShare 样本（录制）→ _format_spot_data 列名映射 → _spot_dict 缓存 → 路由响应的纵向切片
使用的测试方法：TestClient + 真实 app + 录制的 AKShare 样本种入类级缓存（离线回放，不出网）
"""
import pickle

import pytest

pytestmark = pytest.mark.integration

SAMPLE_PATH = "tests/integration/fixtures/akshare/spot_sample.pkl"


@pytest.fixture
def spot_cache():
    """把录制的真实 AKShare 样本 DataFrame 种入 FinanceApiService._spot_dict。"""
    from server.services.finance_api_service import FinanceApiService

    with open(SAMPLE_PATH, "rb") as f:
        df = pickle.load(f)
    FinanceApiService._rebuild_spot_dict(df)
    yield
    FinanceApiService._spot_dict = None  # 清理类级缓存


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
