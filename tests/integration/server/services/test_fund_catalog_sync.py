"""P0-5 白名单同步集成测试：FundCatalogSync ↔ 真实 Postgres。

模块名称：场外 ETF 联接基金白名单批量同步
所测功能：抓取结果 → fund_fee_rules / fund_risk_profiles 幂等 upsert；
         数据不完整时拒绝写库；已有白名单基金不因改名而掉出；
         同步后基金目录可被 FundFeeService 查询到（含风险画像）
使用的测试方法：本地 Supabase 栈 + 合成基金代码 + 数据源替身（集成测试禁止出网，
              故 fetch_jjfl / fetch_basic_info 用录制形态的假数据替换）

注：真实抓取（天天基金页面）由单元测试覆盖解析规则；此处只验证落库与读回链路。
"""
import pytest

from decimal import Decimal

pytestmark = pytest.mark.integration

# 合成基金代码，避免污染 21 条种子数据
测试代码 = ["T90001", "T90002", "T90003"]


def _假jjfl(含分档=True, 申购状态="开放申购", 申购费率=0.0012):
    """构造 fetch_jjfl 的返回形态。"""
    return {
        "purchase_fee_tiers": [{"rate": 申购费率, "amount": 1000000}] if 含分档 else [],
        "redemption_fee_tiers": (
            [{"days": 7, "rate": 0.015}, {"days": 7, "rate": 0.0, "inclusive": True}]
            if 含分档 else []
        ),
        "management_fee_rate": 0.005,
        "custody_fee_rate": 0.001,
        "sales_service_fee_rate": 0.0,
        "min_purchase_amount": 10.0,
        "subscribe_status": 申购状态,
        "redeem_status": "开放赎回",
    }


@pytest.fixture
def 清理测试基金(supabase_client):
    """测试前后都清掉合成基金，保证可重复运行且不污染种子。"""
    def _清():
        for code in 测试代码:
            supabase_client.table("fund_fee_rules").delete().eq("fund_code", code).execute()
            supabase_client.table("fund_risk_profiles").delete().eq("fund_code", code).execute()

    _清()
    yield 测试代码
    _清()


@pytest.fixture
def 同步服务(supabase_client, monkeypatch, 清理测试基金):
    """FundCatalogSync + 数据源替身。返回 (服务, 可变的假数据字典)。"""
    from server.services import fund_catalog_sync as mod

    数据 = {
        "T90001": (_假jjfl(), {"fund_name": "测试沪深300ETF联接A", "ftype": "指数型-股票",
                              "index_name": "沪深300指数", "index_code": "000300"}),
        "T90002": (_假jjfl(), {"fund_name": "测试纳斯达克ETF联接A", "ftype": "指数型-海外股票",
                              "index_name": "纳斯达克100", "index_code": "NDX"}),
        "T90003": (_假jjfl(含分档=False), {"fund_name": "测试缺分档联接A", "ftype": "指数型-股票",
                                         "index_name": "", "index_code": ""}),
    }
    monkeypatch.setattr(mod, "fetch_jjfl", lambda code: 数据.get(code, (None, None))[0])
    monkeypatch.setattr(mod, "fetch_basic_info", lambda code: 数据.get(code, (None, None))[1])

    svc = mod.FundCatalogSync()
    svc._client = supabase_client
    return svc, 数据


def _读费率(supabase_client, code):
    rows = supabase_client.table("fund_fee_rules").select("*").eq("fund_code", code).execute().data
    return rows[0] if rows else None


def _读风险(supabase_client, code):
    rows = supabase_client.table("fund_risk_profiles").select("*").eq("fund_code", code).execute().data
    return rows[0] if rows else None


# ==================== 落库 ====================


def test_同步写入费率规则与风险画像(supabase_client, 同步服务):
    svc, _ = 同步服务
    stats = svc.run(codes=测试代码, interval=0)

    assert stats["synced"] == 2          # T90003 缺分档被拒
    assert stats["skipped"] == 1

    rule = _读费率(supabase_client, "T90001")
    assert rule["fund_name"] == "测试沪深300ETF联接A"
    assert rule["fund_type"] == "of"
    assert rule["share_class"] == "A"
    assert rule["min_purchase_amount"] == 10.0
    assert rule["purchase_fee_tiers"] == [{"rate": 0.0012, "amount": 1000000}]
    assert (rule["confirm_delay"], rule["redeem_settle_delay"]) == (1, 3)

    risk = _读风险(supabase_client, "T90001")
    assert (risk["breadth_score"], risk["volatility_score"],
            risk["market_score"], risk["board_score"]) == (1, 1, 1, 1)
    assert risk["risk_level"] == "moderate"
    assert risk["risk_label"] == "中等风险"


def test_QDII基金落库为T加2七日(supabase_client, 同步服务):
    svc, _ = 同步服务
    svc.run(codes=["T90002"], interval=0)

    rule = _读费率(supabase_client, "T90002")
    assert (rule["confirm_delay"], rule["redeem_settle_delay"]) == (2, 7)
    assert _读风险(supabase_client, "T90002")["market_score"] == 3


def test_费率分档缺失的基金不写库(supabase_client, 同步服务):
    """T90003 申购/赎回分档为空 —— 宁可不支持，也不用默认费率兜底。"""
    svc, _ = 同步服务
    svc.run(codes=["T90003"], interval=0)

    assert _读费率(supabase_client, "T90003") is None
    assert _读风险(supabase_client, "T90003") is None


def test_暂停申购的基金仍写入并记录状态(supabase_client, 同步服务):
    """状态如实落库，能否买交给交易侧判定。

    必须写库：否则基金从「开放申购」转「暂停申购」时旧行原封不动，
    用户仍会买到一只已经暂停申购的基金。
    """
    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="暂停申购"), 数据["T90001"][1])
    stats = svc.run(codes=["T90001"], interval=0)

    assert stats["synced"] == 1
    assert _读费率(supabase_client, "T90001")["subscribe_status"] == "暂停申购"


def test_暂停申购的基金可查到但买入被拒(supabase_client, 同步服务, monkeypatch):
    """端到端：目录里有它（能查、能赎回），但申购被交易链路拦下。"""
    from server.services.portfolio_service import PortfolioService

    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="暂停申购"), 数据["T90001"][1])
    svc.run(codes=["T90001"], interval=0)

    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: supabase_client)
    result = PortfolioService().apply_purchase("暂停申购测试用户", "T90001", Decimal("100"))

    assert result["success"] is False
    assert "暂停申购" in result["message"]


# ==================== 限大额基金 ====================


def test_限大额基金落库并带单日上限(supabase_client, 同步服务):
    """「限大额」是可交易状态（开放申购 + 单日上限），上限随行落库。"""
    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="限大额"),
                      dict(数据["T90001"][1], max_purchase_amount=1000.0))
    stats = svc.run(codes=["T90001"], interval=0)

    assert stats["synced"] == 1
    rule = _读费率(supabase_client, "T90001")
    assert rule["max_purchase_amount"] == 1000.0


def test_开放申购基金的上限为空(supabase_client, 同步服务):
    """开放申购基金 MAXSG 为哨兵值，解析后落库为 NULL（无限额）。"""
    svc, _ = 同步服务
    svc.run(codes=["T90001"], interval=0)
    assert _读费率(supabase_client, "T90001")["max_purchase_amount"] is None


def test_限大额但取不到上限时写入并拒买(supabase_client, 同步服务, monkeypatch):
    """MAXSG 解析失败：写库留痕（可查询、可赎回），但交易侧拒绝申购。

    不写库会让它悄悄消失，且无法区分「不支持」与「抓取失败」；
    写库又不把 NULL 当无限额，是靠交易侧的「限大额 + 上限为空 → 拒买」兜住。
    """
    from server.services.portfolio_service import PortfolioService

    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="限大额"),
                      dict(数据["T90001"][1], max_purchase_amount=None))
    stats = svc.run(codes=["T90001"], interval=0)

    assert stats["synced"] == 1
    rule = _读费率(supabase_client, "T90001")
    assert rule["subscribe_status"] == "限大额"
    assert rule["max_purchase_amount"] is None

    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: supabase_client)
    result = PortfolioService().apply_purchase("缺上限测试用户", "T90001", Decimal("100"))
    assert result["success"] is False
    assert "限额信息暂不可用" in result["message"]


def test_限大额基金超上限申购被拒(supabase_client, 同步服务, monkeypatch):
    """端到端：同步进来的限大额基金，超额下单被交易链路拦下。

    拦截发生在取净值/建账户之前，故无需准备账户资金。
    """
    from server.services.fund_fee_service import FundFeeService
    from server.services.portfolio_service import PortfolioService

    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="限大额"),
                      dict(数据["T90001"][1], max_purchase_amount=1000.0))
    svc.run(codes=["T90001"], interval=0)

    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: supabase_client)
    fee_svc = FundFeeService()
    assert fee_svc.is_supported("T90001") is True

    result = PortfolioService().apply_purchase("限大额测试用户", "T90001", Decimal("5000"))
    assert result["success"] is False
    assert "超过该基金单日累计申购上限" in result["message"]


def test_同一交易日多笔申购累计超上限被拒(supabase_client, 同步服务,
                                           portfolio_service, user_id):
    """端到端（真实 Postgres）：600 元先成交，再下 500 元必须被拦。

    两笔单看都没超 1000 元上限，只有把「同一 T 日」的订单聚合起来才会发现超额 ——
    这验证了 confirm_date 等值筛选在真实 PostgREST 上确实能把两笔归为一组。
    时钟冻结在 2026-09-14（周一）盘中，两笔落在同一 T 日（确认日 T+1 = 09-15）。
    """
    import time_machine
    from datetime import datetime, timedelta, timezone

    svc, 数据 = 同步服务
    数据["T90001"] = (_假jjfl(申购状态="限大额"),
                      dict(数据["T90001"][1], max_purchase_amount=1000.0))
    svc.run(codes=["T90001"], interval=0)

    盘中 = datetime(2026, 9, 14, 14, 0, tzinfo=timezone(timedelta(hours=8)))
    with time_machine.travel(盘中):
        第一笔 = portfolio_service.apply_purchase(
            user_id, "T90001", Decimal("600"), price=Decimal("1.5"))
        assert 第一笔["success"] is True

        第二笔 = portfolio_service.apply_purchase(
            user_id, "T90001", Decimal("500"), price=Decimal("1.5"))

    assert 第二笔["success"] is False
    assert "本交易日已申购 600.00 元" in 第二笔["message"]
    assert "超过该基金单日累计申购上限" in 第二笔["message"]

    # 被拒的一笔在冻结资金之前就返回了，不落库
    orders = (supabase_client.table("trade_orders").select("*")
              .eq("user_id", user_id).execute().data)
    assert len(orders) == 1
    assert orders[0]["status"] == "pending"


# ==================== 幂等性 ====================


def test_重复同步不产生重复行且费率被更新(supabase_client, 同步服务):
    svc, 数据 = 同步服务
    svc.run(codes=["T90001"], interval=0)
    assert _读费率(supabase_client, "T90001")["purchase_fee_tiers"] == [{"rate": 0.0012, "amount": 1000000}]

    # 第二次同步时费率变了（模拟基金调费），应覆盖而不是新增
    数据["T90001"] = (_假jjfl(申购费率=0.0008), 数据["T90001"][1])
    stats = svc.run(codes=["T90001"], interval=0)
    assert stats["synced"] == 1

    rows = supabase_client.table("fund_fee_rules").select("*").eq("fund_code", "T90001").execute().data
    assert len(rows) == 1
    assert rows[0]["purchase_fee_tiers"] == [{"rate": 0.0008, "amount": 1000000}]


# ==================== 发现：已有白名单不被挤掉 ====================


def test_名称发现不到任何基金时_已有白名单仍全部纳入同步(同步服务):
    """改名导致名称筛选失效时，现有白名单基金绝不能从同步目标里消失。

    这是 161831（银华恒生中国企业ETF联接 → 银华恒生国企指数(QDII-LOF)A）
    暴露的问题：并上现有白名单后，这类基金仍会被重新抓取而不是被剔除。
    """
    svc, _ = 同步服务
    白名单 = svc._existing_whitelist_codes()
    assert len(白名单) >= 20, "本地库应有 21 条种子费率规则"

    svc._discover_by_name = lambda: []      # 模拟名称筛选一无所获
    stats = svc.run(interval=0)

    # 目标数恰好等于白名单数 —— 一只都没丢
    assert stats["discovered"] == len(白名单)


def test_名称发现的新基金与白名单并集(同步服务):
    """两侧都要生效：名字筛出的新基金要抓，白名单里的老基金也不能漏。"""
    svc, _ = 同步服务
    白名单 = svc._existing_whitelist_codes()

    svc._discover_by_name = lambda: [
        {"code": "T90002", "name": "测试纳斯达克ETF联接A", "ftype": "指数型-海外股票"}
    ]

    被抓取过的 = []
    原sync_one = svc.sync_one

    def _记录(code):
        被抓取过的.append(code)
        return 原sync_one(code)

    svc.sync_one = _记录
    stats = svc.run(interval=0)

    # 目标数 = 白名单 + 1 只新基金
    assert stats["discovered"] == len(白名单) + 1
    # 新基金被真正处理并写入
    assert "T90002" in stats["codes"]
    # 白名单里的每一只也都进了抓取队列（只是替身数据源里没有，故被跳过）
    assert set(白名单) <= set(被抓取过的)


# ==================== 读回：基金目录查询 ====================


def test_同步后可查询到新基金并附带风险画像(supabase_client, 同步服务):
    from server.services.fund_fee_service import FundFeeService

    svc, _ = 同步服务
    svc.run(codes=["T90001", "T90002"], interval=0)

    fee_svc = FundFeeService()
    fee_svc._client = supabase_client

    found = fee_svc.list_supported_funds(keyword="测试沪深")
    assert found["total"] == 1
    item = found["items"][0]
    assert item["fund_code"] == "T90001"
    assert item["risk_level"] == "moderate"
    assert item["confirm_delay"] == 1


def test_基金详情含费率分档与风险(supabase_client, 同步服务):
    from server.services.fund_fee_service import FundFeeService

    svc, _ = 同步服务
    svc.run(codes=["T90001"], interval=0)

    fee_svc = FundFeeService()
    fee_svc._client = supabase_client

    detail = fee_svc.get_fund_detail("T90001")
    assert detail["redemption_fee_tiers"] == [
        {"days": 7, "rate": 0.015}, {"days": 7, "rate": 0.0, "inclusive": True},
    ]
    assert detail["risk_label"] == "中等风险"


def test_同步进来的新基金可直接完成一笔申购(supabase_client, 同步服务, monkeypatch):
    """端到端：新基金落库后，交易链路无需任何改动即可交易它。"""
    from server.services.fund_fee_service import FundFeeService

    svc, _ = 同步服务
    svc.run(codes=["T90001"], interval=0)

    monkeypatch.setattr("server.storage.supabase_client.get_supabase", lambda: supabase_client)
    fee_svc = FundFeeService()

    # 白名单放行
    assert fee_svc.is_supported("T90001") is True
    # 申购费按落库分档计算（外扣法：10000/(1+0.0012)）
    fee = fee_svc.calc_purchase_fee("T90001", 10000.0)
    assert fee["fee"] == pytest.approx(11.99, abs=0.01)
    # 赎回费按持有天数命中档位
    assert fee_svc.calc_redemption_fee("T90001", 1000.0, 3) == pytest.approx(15.0)
