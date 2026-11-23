"""真实上游契约测试：直连 AKShare/新浪/东财，验证「解析器 ↔ 上游响应」仍然对得上。

模块名称：server/services/finance_api_service.py（上游依赖层）
所测功能：净值/概览/行情三类上游接口在**真实网络**下的可用性与字段解析
使用的测试方法：真实出网 + 真实 akshare，不 mock、不录制

为什么需要这一层（其余两层都盖不到）：
- 单元测试用替身 DataFrame，上游表结构一变（加列、akshare 解析器写死列名）照样全绿；
- 集成测试有出网守卫，按设计看不见任何外部依赖的变化。
真实故障（akshare 1.18.64 的 fund_etf_fund_info_em 抛 Length mismatch；生产服务器到
push2*.eastmoney.com 被应用层拒绝，导致 /kline、分时全空 3 周）
正是这两层都照不到的盲区。

数据源分工（2026-10-26 起）：
- 净值 → 只读 DB（`fund_nav`），**不再有上游回退**，因此本文件不再测净值上游；
  目录外代码（场内 ETF）直接抛 `FundNotSupported`，见 `test_目录外代码_不回退上游`；
- K线/分时 → 新浪，见 docs/20-设计/行情/行情数据源.md；
- 详情概览（/detail）→ 东财 fund.eastmoney.com，该域名生产可达，未改。

运行方式（**默认不跑**，需真实出网，且行情用例要跑在能访问新浪 hq.sinajs.cn 的机器上）：
    poetry run pytest tests/integration/server/services/test_upstream_contract.py -m integration_net

生产服务器上跑最有意义（服务器出口与线上一致）：
    cd /root/ai-etf && .venv/bin/python -m pytest tests/integration/server/services/test_upstream_contract.py -m integration_net
"""
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.integration_net]

# 场内 ETF + 场外基金各一只：详情概览对两类代码都要能取到
FUND_CODES = ["512890", "110020"]


@pytest.fixture(scope="module")
def svc():
    from server.services.finance_api_service import FinanceApiService

    return FinanceApiService()


def test_目录外代码_不回退上游(svc):
    """2026-10-26 决策：目录外代码（场内 ETF 等）不查净值、不回退上游。

    若哪天又给 `_query_nav_history` 加回 `fund_open_fund_info_em` 回退，
    这条会立刻失败——这是「搜不到、买不了，却在详情页看得见」的防线。
    """
    from server.services.fund_nav_service import FundNotSupported

    with pytest.raises(FundNotSupported):
        svc._query_nav_history("512890", limit=5)


@pytest.mark.parametrize("fund_code", FUND_CODES)
def test_详情概览_字段可解析(svc, fund_code):
    """概览接口（名称/费率/规模）是详情页已正常展示的部分，作为上游可用性的基线。"""
    overview = svc._query_detail_overview(fund_code)

    assert overview, f"{fund_code} 未取到概览"
    assert overview["full_name"]
    assert overview["net_asset_scale"]


def test_K线_日线与周线都可取到(svc):
    """K线换源后仍要取到真实序列；周线由日线重采样，必须与日线口径一致地非空。"""
    daily = svc.query_kline("512890", period="daily", limit=5)
    assert len(daily) == 5, "未取到 5 条日K"
    assert all(item["date"] and item["close"] > 0 for item in daily)
    assert [item["date"] for item in daily] == sorted(item["date"] for item in daily), "日K未按日期升序"

    weekly = svc.query_kline("512890", period="weekly", limit=5)
    assert len(weekly) == 5, "周线重采样后取不到 5 条"
    assert all(item["close"] > 0 for item in weekly)


def test_分时_只返回当日且时间轴不越界(svc):
    """新浪分钟接口是约 1970 根的滚动窗口（跨多个交易日），必须按当日过滤。

    不过滤会把十几天的走势画成一天——这是换源时最容易踩的坑。
    """
    items = svc.query_intraday("512890")
    assert items, "未取到分时数据"
    # 真实分时数据带 amount；模拟降级数据不带，据此区分后再校验时间轴
    if "amount" in items[0]:
        assert all("09:30" <= i["time"] <= "15:00" for i in items), "分时时间轴越界"
        assert len(items) <= 241, f"当日分时不应超过 241 个点，实际 {len(items)} 个"
    assert isinstance(items[0]["change_pct"], (int, float))
