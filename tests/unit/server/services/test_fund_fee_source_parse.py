"""fund_fee_source 解析层单元测试：天天基金 jjfl 页面文本 → 费率分档。

模块名称：server/services/fund_fee_source.py
所测功能：parse_purchase_tiers / parse_redemption_tiers / parse_share_class
         及 _num_cn / _pct / _fixed_fee / _amount 等数值解析工具
测试方法：纯函数直测（只喂页面文本，不发起任何请求），不联网、不连 Supabase。

关键口径：
- 申购费率取**平台优惠费率**（页面列形如「原费率|优惠费率」，取竖线后一段）；
- 赎回档的 days 是「排他上界」，即下一档的起始持有天数；
- 期限单位混用 年/个月/天，统一折算（1年=365天、1个月=30天），与现有种子一致。
"""
import pytest

from server.services.fund_fee_source import (
    _amount,
    _fixed_fee,
    _num_cn,
    _pct,
    _rnd,
    parse_max_purchase_amount,
    parse_purchase_tiers,
    parse_redemption_tiers,
    parse_share_class,
)


# ==================== 数值解析工具 ====================


@pytest.mark.parametrize("文本,期望", [
    ("100万元", 1000000.0),
    ("1,000万元", 10000000.0),
    ("1000元", 1000.0),
    ("10.00元", 10.0),
    ("---", None),
    ("", None),
    (None, None),
])
def test_金额文本转数值(文本, 期望):
    assert _num_cn(文本) == 期望


@pytest.mark.parametrize("文本,期望", [
    ("1.50%", 0.015),
    ("0.00%", 0.0),
    ("每笔1000元", None),   # 不是百分比
    ("---", None),
    (None, None),
])
def test_百分比文本转小数(文本, 期望):
    assert _pct(文本) == 期望


def test_固定费用文本解析():
    assert _fixed_fee("每笔1000元") == 1000.0
    assert _fixed_fee("每笔 1000.00 元") == 1000.0
    assert _fixed_fee("1.50%") is None


def test_浮点误差归一():
    assert _rnd(0.0007000000000000001) == 0.0007


def test_金额归一为整数():
    assert _amount(1000000.0) == 1000000
    assert _amount(500.5) == 500.5
    assert _amount(None) is None


# ==================== 申购费率分档 ====================


def test_申购取平台优惠费率():
    """页面列「原费率|优惠费率」时取后者 —— 与现有种子一致。"""
    tiers = parse_purchase_tiers([("小于100万元", "0.15%|0.12%")])
    assert tiers == [{"rate": 0.0012, "amount": 1000000}]


def test_申购无折扣时直接取该费率():
    tiers = parse_purchase_tiers([("小于500万元", "0.10%")])
    assert tiers == [{"rate": 0.001, "amount": 5000000}]


def test_申购金额单位万元换算():
    tiers = parse_purchase_tiers([("小于1000万元", "0.02%")])
    assert tiers == [{"rate": 0.0002, "amount": 10000000}]


def test_申购金额单位为元():
    tiers = parse_purchase_tiers([("小于1000元", "0.50%")])
    assert tiers == [{"rate": 0.005, "amount": 1000}]


def test_申购末档大于等于标记inclusive():
    tiers = parse_purchase_tiers([("大于等于500万元", "0.05%")])
    assert tiers == [{"rate": 0.0005, "amount": 5000000, "inclusive": True}]


def test_申购固定费用档放最后作为兜底():
    """「每笔N元」不区分金额，作为万能兜底档排在金额档之后。"""
    rows = [("小于100万元", "0.12%"), ("大于等于1000万元", "每笔1000元")]
    assert parse_purchase_tiers(rows) == [
        {"rate": 0.0012, "amount": 1000000},
        {"rate": 0, "fixed_fee": 1000.0},
    ]


def test_申购C类全免为无金额兜底档():
    """C 类申购费率列常为「---」，解析为匹配任意金额的 0 费率档。"""
    assert parse_purchase_tiers([("---", "0.00%")]) == [{"rate": 0.0}]


def test_申购有效金额分档与兜底档共存():
    """真实形态：多档金额 + 末档固定费用（110020 即此形态）。"""
    rows = [
        ("小于100万元", "0.15%|0.12%"),
        ("大于等于100万元，小于500万元", "0.10%|0.08%"),
        ("大于等于1000万元", "每笔1000元"),
    ]
    assert parse_purchase_tiers(rows) == [
        {"rate": 0.0012, "amount": 1000000},
        {"rate": 0.0008, "amount": 5000000},
        {"rate": 0, "fixed_fee": 1000.0},
    ]


# ==================== 赎回费率分档 ====================


def test_赎回天数档_小于N天():
    assert parse_redemption_tiers([("小于7天", "1.50%")]) == [{"days": 7, "rate": 0.015}]


def test_赎回天数档_小于等于N天取N加1():
    """「小于等于N天」的排他上界是 N+1，否则第 N+1 天会落错档。"""
    assert parse_redemption_tiers([("小于等于7天", "1.50%")]) == [{"days": 8, "rate": 0.015}]


def test_赎回期限按年折算为365天():
    """页面用「大于等于7天，小于1年」表述，上界折算 365 天（与种子一致）。"""
    rows = [("大于等于7天，小于1年", "0.50%")]
    assert parse_redemption_tiers(rows) == [{"days": 365, "rate": 0.005}]


def test_赎回末档大于等于N年标记inclusive():
    rows = [("大于等于2年", "0.00%")]
    assert parse_redemption_tiers(rows) == [{"days": 730, "rate": 0.0, "inclusive": True}]


def test_赎回期限按个月折算为30天():
    rows = [("大于等于1个月，小于3个月", "0.50%")]
    assert parse_redemption_tiers(rows) == [{"days": 90, "rate": 0.005}]


def test_赎回完整年档组合_000051形态():
    """000051 华夏沪深300ETF联接A 真实页面：<7天 / ≥7天且<1年 / ≥1年。"""
    rows = [
        ("小于7天", "1.50%"),
        ("大于等于7天，小于1年", "0.50%"),
        ("大于等于1年", "0.00%"),
    ]
    assert parse_redemption_tiers(rows) == [
        {"days": 7, "rate": 0.015},
        {"days": 365, "rate": 0.005},
        {"days": 365, "rate": 0.0, "inclusive": True},
    ]


def test_赎回完整年档组合_001180形态():
    """001180 广发医药卫生联接A 真实页面：多出一个「1年~2年」档。"""
    rows = [
        ("小于7天", "1.50%"),
        ("大于等于7天，小于1年", "0.50%"),
        ("大于等于1年，小于2年", "0.30%"),
        ("大于等于2年", "0.00%"),
    ]
    assert parse_redemption_tiers(rows) == [
        {"days": 7, "rate": 0.015},
        {"days": 365, "rate": 0.005},
        {"days": 730, "rate": 0.003},
        {"days": 730, "rate": 0.0, "inclusive": True},
    ]


def test_赎回无期限表述的行被丢弃_不做臆造():
    """货基页面写「本基金不收取赎回费用。」+ 长文本条款，无期限。

    此类行必须丢弃而不是补一个 {days: 0} —— 臆造的档位会在计费时被误命中。
    丢弃后 tiers 为空，写入侧据此拒绝该基金（宁可少支持，不可错计费）。
    """
    rows = [
        ("本基金不收取赎回费用。", "0.00%"),
        ("出现下列情形之一时按1%征收强制赎回费……", "1.00%"),
    ]
    assert parse_redemption_tiers(rows) == []


def test_赎回无费率文本的行被跳过():
    assert parse_redemption_tiers([("小于7天", "---")]) == []


# ==================== 份额类别解析 ====================


@pytest.mark.parametrize("名称,期望", [
    ("华夏沪深300ETF联接A", "A"),
    ("天弘中证银行ETF联接C", "C"),
    ("易方达科创50ETF联接E", "E"),
    ("某某联接基金I", "I"),
    ("某某联接基金Y", "Y"),
    ("某某联接基金D", "D"),
    ("某某联接基金F", "F"),
])
def test_份额类别取名称末位字母(名称, 期望):
    assert parse_share_class(名称) == 期望


@pytest.mark.parametrize("名称", [
    "银华恒生中国企业ETF联接",      # 末位「接」
    "某某ETF联接人民币",             # 末位「币」
    "天弘余额宝货币市场基金",         # 末位「金」
    "",                             # 空串
    None,
])
def test_份额类别无法识别时默认A(名称):
    assert parse_share_class(名称) == "A"


# ==================== 单日累计申购上限（MAXSG） ====================


def test_限大额基金解析出真实上限():
    """实测 012348 天弘恒生科技ETF联接A 的 MAXSG=1000。"""
    assert parse_max_purchase_amount("1000") == 1000
    assert parse_max_purchase_amount(1000) == 1000


def test_开放申购基金的哨兵值视为无限额():
    """实测 110020/000071/161831 等开放申购基金 MAXSG=100000000000。"""
    assert parse_max_purchase_amount("100000000000") is None
    assert parse_max_purchase_amount(100000000000) is None


def test_哨兵值用阈值判定而非等值():
    """哨兵值本身无语义，被调整成别的巨大数也不该让逻辑失效。"""
    assert parse_max_purchase_amount(20000000000) is None


def test_上限缺失或非法时视为无限额():
    for 值 in [None, "", "---", "abc", 0, -1]:
        assert parse_max_purchase_amount(值) is None, 值


def test_上限保留小数():
    assert parse_max_purchase_amount("1000.5") == 1000.5

