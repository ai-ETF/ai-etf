"""真实上游契约测试：直连 AKShare/东财，验证「解析器 ↔ 上游响应」仍然对得上。

模块名称：server/services/finance_api_service.py（上游依赖层）
所测功能：净值/概览/行情三类上游接口在**真实网络**下的可用性与字段解析
使用的测试方法：真实出网 + 真实 akshare，不 mock、不录制

为什么需要这一层（其余两层都盖不到）：
- 单元测试用替身 DataFrame，上游表结构一变（东财加列、akshare 解析器写死列名）照样全绿；
- 集成测试有出网守卫，按设计看不见任何外部依赖的变化。
真实故障（akshare 1.18.64 的 fund_etf_fund_info_em 抛 Length mismatch、生产服务器
到 push2*.eastmoney.com 被重置）正是这两层都照不到的盲区。

运行方式（**默认不跑**，需真实出网，且行情用例要跑在能访问东财 push2 的机器上）：
    poetry run pytest tests/integration/server/services/test_upstream_contract.py -m integration_net

生产服务器上跑最有意义（服务器出口与线上一致）：
    cd /root/ai-etf && .venv/bin/python -m pytest tests/integration/server/services/test_upstream_contract.py -m integration_net
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.integration_net]

# 场内 ETF + 场外基金各一只：两类基金走同一净值接口，任一失效都该被抓到
FUND_CODES = ["512890", "110020"]


@pytest.fixture(scope="module")
def svc():
    from server.services.finance_api_service import FinanceApiService

    return FinanceApiService()


@pytest.mark.parametrize("fund_code", FUND_CODES)
def test_历史净值_按代码返回且字段可解析(svc, fund_code):
    """上游净值接口必须按传入代码返回，且单位/累计净值、日增长率都解析得出来。"""
    nav = svc._query_nav_history(fund_code, limit=5)

    assert len(nav) == 5, f"{fund_code} 未取到净值，上游接口可能已变更或不可达"
    assert all(item["date"] and item["nav"] is not None for item in nav)
    assert all(item["daily_growth"] is not None for item in nav)
    # 累计净值允许缺失（单独一次请求），但取到时要等于或大于单位净值（分红过的基金更大）
    assert all(item["accumulated_nav"] is None or item["accumulated_nav"] >= item["nav"] for item in nav)


@pytest.mark.parametrize("fund_code", FUND_CODES)
def test_详情概览_字段可解析(svc, fund_code):
    """概览接口（名称/费率/规模）是详情页已正常展示的部分，作为上游可用性的基线。"""
    overview = svc._query_detail_overview(fund_code)

    assert overview, f"{fund_code} 未取到概览"
    assert overview["full_name"]
    assert overview["net_asset_scale"]


def test_实时行情_数据源可达(svc):
    """环境哨兵：服务器出口到东财 push2 域名必须可达。

    生产服务器一度整体被拒（RemoteDisconnected），导致 /spot、/ranking、/kline、
    分时全空。此断言就是为了让这种环境问题在部署后立刻暴露，而不是等前端报障。
    """
    from server.services.finance_api_service import FinanceApiService

    assert FinanceApiService.refresh_spot_cache(), (
        "全量行情刷新失败：确认服务器能访问东财行情接口（push2delay.eastmoney.com）"
    )
    assert FinanceApiService().query_spot("512890"), "行情缓存里没有 512890，行情数据源可能异常"
