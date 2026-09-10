"""fund_fee_service 单元测试：场外基金申赎费率计算。

模块名称：server/services/fund_fee_service.py
所测功能：申购费选档与计算、赎回费计算、白名单校验、费率规则查询、读值兜底
测试方法：依赖注入（rule 参数 / 替换 svc._client），全程不联网、不连 Supabase。

费率样本取自真实配置 docs/legacy_sql/fund_fee_rules_seed.sql。

覆盖范围说明（规则缺失一律「直接暴露错误」，不做默认值兜底）：
- 申购侧 purchase_fee_tiers 缺失/为空  → calc_purchase_fee 返回 None（拒绝交易）
- 档位选择器收到空档位                  → _match_purchase_tier 抛 ValueError
- 赎回侧 redemption_fee_tiers 缺失/为空 → calc_redemption_fee 返回 None（拒绝）
- 延迟天数 / 起购金额字段缺失           → 抛 ValueError，不再默认 T+1 / T+3 / 10 元
"""
import json

import pytest

from server.services.fund_fee_service import FundFeeService

# ==================== 真实费率样本 ====================

# 110020 易方达沪深300ETF联接A：申购费随金额递减，1000万及以上每笔固定 1000 元
FUND_A_RULE = {
    "fund_code": "110020",
    "fund_name": "易方达沪深300ETF联接A",
    "fund_type": "of",
    "share_class": "A",
    "purchase_fee_tiers": [
        {"amount": 1000000, "rate": 0.0012},
        {"amount": 5000000, "rate": 0.0008},
        {"amount": 10000000, "rate": 0.0002},
        {"rate": 0, "fixed_fee": 1000},
    ],
    "redemption_fee_tiers": [
        {"days": 7, "rate": 0.0150},
        {"days": 365, "rate": 0.0050},
        {"days": 730, "rate": 0.0025},
        {"days": 730, "rate": 0.0000, "inclusive": True},
    ],
    "min_purchase_amount": 10.00,
    "confirm_delay": 1,
    "redeem_settle_delay": 3,
}

# 001595 天弘中证银行ETF联接C：C 类申购费全免（无 amount 的兜底档）
FUND_C_RULE = {
    "fund_code": "001595",
    "fund_name": "天弘中证银行ETF联接C",
    "fund_type": "of",
    "share_class": "C",
    "purchase_fee_tiers": [{"rate": 0.0000}],
    "redemption_fee_tiers": [
        {"days": 7, "rate": 0.0150},
        {"days": 7, "rate": 0.0000, "inclusive": True},
    ],
    "min_purchase_amount": 10.00,
    "confirm_delay": 1,
    "redeem_settle_delay": 3,
}

A_TIERS = FUND_A_RULE["purchase_fee_tiers"]


# ==================== 替身：模拟 Supabase client ====================


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """模拟 supabase 的链式调用 table().select().eq()/.in_().execute()。"""

    def __init__(self, client):
        self._client = client
        self._filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def in_(self, column, values):
        self._client.in_values_seen.append(list(values))
        self._filters[column] = list(values)
        return self

    def execute(self):
        if self._client.error is not None:
            raise self._client.error
        rows = list(self._client.rows)
        if self._client.apply_filters:
            for column, value in self._filters.items():
                if isinstance(value, list):
                    rows = [r for r in rows if r.get(column) in value]
                else:
                    rows = [r for r in rows if r.get(column) == value]
        return FakeResult(rows)


class FakeClient:
    """替身演员：按查询条件在内存行集合里筛选，不产生任何网络 IO。"""

    def __init__(self, rows=None, error=None, apply_filters=True):
        self.rows = list(rows or [])
        self.error = error
        self.apply_filters = apply_filters
        self.in_values_seen = []

    def table(self, _name):
        return FakeQuery(self)


@pytest.fixture
def svc():
    """注入了两句真实费率规则的 service。"""
    service = FundFeeService()
    service._client = FakeClient([FUND_A_RULE, FUND_C_RULE])
    return service


# ==================== _match_purchase_tier：选档 ====================


def test_小额申购命中第一档():
    tier = FundFeeService._match_purchase_tier(A_TIERS, 10000)
    assert tier["rate"] == 0.0012


def test_中间金额命中对应档位():
    tier = FundFeeService._match_purchase_tier(A_TIERS, 3000000)
    assert tier["rate"] == 0.0008


def test_金额恰好等于分界点_非inclusive档不命中而落到下一档():
    # 1000000 < 1000000 不成立，因此不走 0.0012 档
    tier = FundFeeService._match_purchase_tier(A_TIERS, 1000000)
    assert tier["rate"] == 0.0008


def test_金额恰好等于最高分界点_落到无amount兜底档():
    # 10000000 < 10000000 不成立 → 所有金额档都不命中 → 取 fixed_fee 兜底档
    tier = FundFeeService._match_purchase_tier(A_TIERS, 10000000)
    assert tier["fixed_fee"] == 1000


def test_超过所有分界点_命中无amount兜底档():
    tier = FundFeeService._match_purchase_tier(A_TIERS, 15000000)
    assert tier == {"rate": 0, "fixed_fee": 1000}


def test_inclusive为真时_金额等于分界点命中该档():
    tiers = [{"amount": 1000000, "rate": 0.0015, "inclusive": True}, {"rate": 0.001}]
    tier = FundFeeService._match_purchase_tier(tiers, 1000000)
    assert tier["rate"] == 0.0015


def test_全部为无amount档位时_直接返回该档():
    # C 类全免申购费
    tier = FundFeeService._match_purchase_tier([{"rate": 0.0000}], 10000)
    assert tier["rate"] == 0.0000


def test_无兜底档且超过所有分界点时_返回金额最大的档():
    tiers = [{"amount": 1000000, "rate": 0.0012}, {"amount": 5000000, "rate": 0.0008}]
    tier = FundFeeService._match_purchase_tier(tiers, 9000000)
    assert tier["rate"] == 0.0008


def test_档位乱序传入_结果与顺序无关():
    shuffled = list(reversed(A_TIERS))
    assert (
        FundFeeService._match_purchase_tier(shuffled, 3000000)["rate"]
        == FundFeeService._match_purchase_tier(A_TIERS, 3000000)["rate"]
    )


def test_空档位列表_抛出异常而非猜默认费率():
    # 旧实现返回 {"rate": 0.0015}，会把配错静默变成一个看似合理的费率
    with pytest.raises(ValueError):
        FundFeeService._match_purchase_tier([], 10000)


# ==================== calc_purchase_fee：算钱 ====================


def test_比例费率档_按外扣法反算净申购金额(svc):
    # 净额 = 金额 / (1 + 费率)，费用 = 金额 - 净额
    result = svc.calc_purchase_fee("110020", 10000, rule=FUND_A_RULE)
    assert result["net_amount"] == 9988.01
    assert result["fee"] == 11.99


def test_比例费率档_费用与净额之和等于申购金额(svc):
    result = svc.calc_purchase_fee("110020", 3000000, rule=FUND_A_RULE)
    assert result["fee"] + result["net_amount"] == pytest.approx(3000000, abs=0.01)


def test_固定费用档_费用为固定值且不按比例(svc):
    result = svc.calc_purchase_fee("110020", 15000000, rule=FUND_A_RULE)
    assert result["fee"] == 1000
    assert result["net_amount"] == 14999000


def test_C类份额_申购费为零且全额买入(svc):
    result = svc.calc_purchase_fee("001595", 10000, rule=FUND_C_RULE)
    assert result["fee"] == 0.0
    assert result["net_amount"] == 10000


def test_固定费用优先于费率_两者并存时取固定费用(svc):
    rule = {"purchase_fee_tiers": [{"amount": 5000000, "rate": 0.01, "fixed_fee": 100}]}
    result = svc.calc_purchase_fee("000000", 1000, rule=rule)
    assert result["fee"] == 100
    assert result["net_amount"] == 900


def test_档位为JSON字符串_能正确解析(svc):
    rule = {"purchase_fee_tiers": json.dumps([{"amount": 1000000, "rate": 0.0015}])}
    result = svc.calc_purchase_fee("000000", 1000, rule=rule)
    assert result["fee"] == 1.50
    assert result["net_amount"] == 998.50


def test_基金不在白名单_返回None表示拒绝交易(svc):
    assert svc.calc_purchase_fee("999999", 10000) is None


def test_申购档位缺失_返回None拒绝而非套用默认费率(svc):
    # 旧实现在此处静默套用 0.0015，会把钱按猜出来的费率算完
    assert svc.calc_purchase_fee("000000", 10000, rule={"purchase_fee_tiers": None}) is None


def test_申购档位为空列表_返回None拒绝(svc):
    assert svc.calc_purchase_fee("000000", 10000, rule={"purchase_fee_tiers": []}) is None


def test_申购档位为空JSON字符串_返回None拒绝(svc):
    # "[]" 是真值字符串，解析后为空列表，同样应拒绝
    assert svc.calc_purchase_fee("000000", 10000, rule={"purchase_fee_tiers": "[]"}) is None


# ==================== calc_redemption_fee：赎回费 ====================


def test_持有不足7天_按最高档收百分之一点五(svc):
    assert svc.calc_redemption_fee("110020", 10000, 3, rule=FUND_A_RULE) == 150.0


def test_持有100天_按365天档收百分之零点五(svc):
    assert svc.calc_redemption_fee("110020", 10000, 100, rule=FUND_A_RULE) == 50.0


def test_持有恰好7天_非inclusive档不命中而落到365天档(svc):
    assert svc.calc_redemption_fee("110020", 10000, 7, rule=FUND_A_RULE) == 50.0


def test_持有恰好365天_落到730天档(svc):
    assert svc.calc_redemption_fee("110020", 10000, 365, rule=FUND_A_RULE) == 25.0


def test_持有恰好730天_inclusive档命中_免赎回费(svc):
    assert svc.calc_redemption_fee("110020", 10000, 730, rule=FUND_A_RULE) == 0.0


def test_持有超过730天_无档位命中_费率为零(svc):
    assert svc.calc_redemption_fee("110020", 10000, 800, rule=FUND_A_RULE) == 0.0


def test_金额含小数_结果四舍五入到两位(svc):
    assert svc.calc_redemption_fee("110020", 1234.567, 3, rule=FUND_A_RULE) == 18.52


def test_赎回档位为字典形式_取其中tiers字段(svc):
    rule = {"redemption_fee_tiers": {"tiers": [{"days": 7, "rate": 0.015}]}}
    assert svc.calc_redemption_fee("000000", 10000, 3, rule=rule) == 150.0


def test_基金不在白名单_赎回费返回None(svc):
    assert svc.calc_redemption_fee("999999", 10000, 3) is None


def test_赎回档位缺失_返回None拒绝而非免赎回费(svc):
    # 原实现返回 0.0（等于免手续费放行），已修正为拒绝
    assert svc.calc_redemption_fee("000000", 10000, 3, rule={"redemption_fee_tiers": None}) is None


def test_赎回档位为空列表_返回None拒绝(svc):
    assert svc.calc_redemption_fee("000000", 10000, 3, rule={"redemption_fee_tiers": []}) is None


def test_赎回档位为JSON字符串_能正确解析(svc):
    rule = {"redemption_fee_tiers": json.dumps([{"days": 7, "rate": 0.015}])}
    assert svc.calc_redemption_fee("000000", 10000, 3, rule=rule) == 150.0


def test_赎回档位为不可识别类型_视为无档位并拒绝(svc):
    assert svc.calc_redemption_fee("000000", 10000, 3, rule={"redemption_fee_tiers": 123}) is None


# ==================== is_supported ====================


def test_白名单命中_支持交易(svc):
    assert svc.is_supported("110020") is True


def test_白名单未命中_不支持交易(svc):
    assert svc.is_supported("999999") is False


def test_查询异常时_视为不支持交易(svc):
    svc._client = FakeClient(error=RuntimeError("连接失败"))
    assert svc.is_supported("110020") is False


# ==================== get_fee_rule ====================


def test_单基金查询命中_返回该行规则(svc):
    rule = svc.get_fee_rule("110020")
    assert rule["fund_name"] == "易方达沪深300ETF联接A"


def test_单基金查询未命中_返回None(svc):
    assert svc.get_fee_rule("999999") is None


def test_单基金查询抛异常_返回None不向上抛出(svc):
    svc._client = FakeClient(error=RuntimeError("连接失败"))
    assert svc.get_fee_rule("110020") is None


def test_数据库未配置时_返回None(monkeypatch):
    # 模拟 get_supabase() 因环境变量缺失返回 None，不产生任何外部 IO
    import server.storage.supabase_client as supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: None)
    assert FundFeeService().get_fee_rule("110020") is None


# ==================== get_fee_rules_batch ====================


def test_批量查询_返回代码到规则的映射(svc):
    rules = svc.get_fee_rules_batch(["110020", "001595"])
    assert set(rules) == {"110020", "001595"}
    assert rules["110020"]["fund_name"] == "易方达沪深300ETF联接A"


def test_批量查询入参去重后才查库(svc):
    svc.get_fee_rules_batch(["110020", "110020", "110020"])
    assert svc._client.in_values_seen == [["110020"]]


def test_批量查询传空列表_直接返回空字典且不查库(svc):
    assert svc.get_fee_rules_batch([]) == {}
    assert svc._client.in_values_seen == []


def test_批量查询_查不到的基金不出现在结果中(svc):
    rules = svc.get_fee_rules_batch(["110020", "999999"])
    assert set(rules) == {"110020"}


def test_批量查询_跳过缺少基金代码的脏数据行():
    service = FundFeeService()
    # 关闭条件下推，模拟数据库返回一条无 fund_code 的脏数据
    service._client = FakeClient([{"fund_name": "脏数据"}, FUND_A_RULE], apply_filters=False)
    assert set(service.get_fee_rules_batch(["110020"])) == {"110020"}


def test_批量查询抛异常_返回空字典(svc):
    svc._client = FakeClient(error=RuntimeError("连接失败"))
    assert svc.get_fee_rules_batch(["110020"]) == {}


def test_批量查询_数据库未配置时返回空字典(monkeypatch):
    import server.storage.supabase_client as supabase_client

    monkeypatch.setattr(supabase_client, "get_supabase", lambda: None)
    assert FundFeeService().get_fee_rules_batch(["110020"]) == {}


# ==================== get_min_purchase_amount ====================


def test_起购金额_返回配置值(svc):
    assert svc.get_min_purchase_amount("110020", rule=FUND_A_RULE) == 10.0


def test_起购金额字段缺失_抛错而非默认10元(svc):
    with pytest.raises(ValueError):
        svc.get_min_purchase_amount("000000", rule={})


def test_起购金额配置为0_表示无门槛并原样返回(svc):
    # 旧实现用 `or 10.0` 把 0 当作缺失，会凭空冒出一个起购门槛
    assert svc.get_min_purchase_amount("000000", rule={"min_purchase_amount": 0}) == 0.0


def test_起购金额_基金不支持时抛错(svc):
    with pytest.raises(ValueError):
        svc.get_min_purchase_amount("999999")


# ==================== get_confirm_delay ====================


def test_确认延迟_返回配置值(svc):
    assert svc.get_confirm_delay("110020", rule={"confirm_delay": 2}) == 2


def test_确认延迟字段缺失_抛错而非默认T加1(svc):
    with pytest.raises(ValueError):
        svc.get_confirm_delay("000000", rule={})


def test_确认延迟配置为0_保留0不当作缺失(svc):
    assert svc.get_confirm_delay("000000", rule={"confirm_delay": 0}) == 0


def test_确认延迟_基金不支持时抛错(svc):
    with pytest.raises(ValueError):
        svc.get_confirm_delay("999999")


# ==================== get_redeem_settle_delay ====================


def test_赎回到账延迟_返回配置值(svc):
    assert svc.get_redeem_settle_delay("110020", rule={"redeem_settle_delay": 7}) == 7


def test_赎回到账延迟字段缺失_抛错而非默认T加3(svc):
    with pytest.raises(ValueError):
        svc.get_redeem_settle_delay("000000", rule={})


def test_赎回到账延迟配置为0_保留0不当作缺失(svc):
    assert svc.get_redeem_settle_delay("000000", rule={"redeem_settle_delay": 0}) == 0


def test_赎回到账延迟_基金不支持时抛错(svc):
    with pytest.raises(ValueError):
        svc.get_redeem_settle_delay("999999")


# ==================== get_fund_name ====================


def test_基金名称_返回配置值(svc):
    assert svc.get_fund_name("001595", rule=FUND_C_RULE) == "天弘中证银行ETF联接C"


def test_基金名称字段缺失_返回None(svc):
    assert svc.get_fund_name("000000", rule={}) is None


def test_基金名称_基金不支持时返回None(svc):
    assert svc.get_fund_name("999999") is None
