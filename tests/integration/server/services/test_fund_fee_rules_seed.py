"""P0-4 费率规则集成测试：FundFeeService ↔ 真实 Postgres（fund_fee_rules 种子数据）。

模块名称：场外基金手续费规则服务
所测功能：真实数据库读费率规则、申购/赎回档位匹配、查不到即拒单
使用的测试方法：本地 Supabase 栈 + 21 条真实种子费率规则 + 注入本地库 client
"""
import pytest

pytestmark = pytest.mark.integration


def test_种子数据_费率规则至少20条(supabase_client):
    resp = supabase_client.table("fund_fee_rules").select("count", count="exact").execute()
    assert resp.count >= 20


def test_get_fee_rule_命中真实基金(fee_service):
    rule = fee_service.get_fee_rule("110020")
    assert rule is not None
    assert rule["fund_name"] == "易方达沪深300ETF联接A"
    assert rule["fund_type"] == "of"
    assert rule["share_class"] == "A"


def test_get_fee_rule_查不到返回None_拒绝交易(fee_service):
    # 查不到规则即拒绝交易，不允许默认费率兜底
    assert fee_service.get_fee_rule("999999") is None
    assert fee_service.is_supported("999999") is False


def test_get_fee_rules_batch_去重且查不到的不出现(fee_service):
    rules = fee_service.get_fee_rules_batch(["110020", "110020", "999999"])
    assert set(rules.keys()) == {"110020"}


def test_calc_purchase_fee_C类申购费全免(fee_service):
    # 001595 天弘中证银行ETF联接C，purchase_fee_tiers=[{"rate": 0.0}]
    result = fee_service.calc_purchase_fee("001595", 1000.0)
    assert result == {"fee": 0.0, "net_amount": 1000.0}


def test_calc_purchase_fee_A类外扣法(fee_service):
    # 110020 申购 10000 元 → 命中第一档 rate=0.0012（外扣法）
    result = fee_service.calc_purchase_fee("110020", 10000.0)
    assert result["fee"] == pytest.approx(11.99, abs=0.01)
    assert result["net_amount"] == pytest.approx(9988.01, abs=0.01)


def test_calc_purchase_fee_大额命中固定费用兜底档(fee_service):
    # 110020 申购 2000 万 → 所有金额档位未命中 → 兜底固定费用 1000 元
    result = fee_service.calc_purchase_fee("110020", 20000000.0)
    assert result == {"fee": 1000.0, "net_amount": 19999000.0}


def test_calc_redemption_fee_持有天数匹配档位(fee_service):
    # 110020 redemption tiers: <7天 1.5%，7~365天 0.5%
    assert fee_service.calc_redemption_fee("110020", 1000.0, 3) == pytest.approx(15.0)
    assert fee_service.calc_redemption_fee("110020", 1000.0, 30) == pytest.approx(5.0)


def test_get_min_purchase_amount_真实规则字段(fee_service):
    # 110020 / 001595 的 min_purchase_amount 均为 10 元
    assert fee_service.get_min_purchase_amount("110020") == pytest.approx(10.0)
    assert fee_service.get_min_purchase_amount("001595") == pytest.approx(10.0)
