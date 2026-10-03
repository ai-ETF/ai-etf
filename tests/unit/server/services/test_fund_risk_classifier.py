"""fund_risk_classifier 单元测试：基金属性 → 四维风险分自动分级。

模块名称：server/services/fund_risk_classifier.py
所测功能：classify_fund（基金名称/跟踪标的/类型 → 四维分 + 风险等级 + 待复核标记）
测试方法：纯函数直测，不联网、不连 Supabase。

核心回归基线：现有 fund_risk_profiles 的 20 条**人工打分**必须能被自动分类复现
（见 supabase/migrations/20260821155107_create_fund_risk_profiles.sql）。
这 20 条是设计文档判定标准的既有落地，自动规则若与之不符即为规则有误。
"""
import pytest

from server.services.fund_risk_classifier import classify_fund


# (基金简称, 指数广度, 波动属性, 市场属性, 板块特征) —— 均取自现有 20 条人工打分
基线20只 = [
    ("易方达沪深300ETF联接A",       1, 1, 1, 1),
    ("天弘中证银行ETF联接A",         2, 1, 1, 1),
    ("天弘中证银行ETF联接C",         2, 1, 1, 1),
    ("天弘中证食品饮料ETF联接A",     2, 2, 1, 1),
    ("广发中证基建工程ETF联接A",     2, 2, 1, 1),
    ("国泰中证全指通信设备ETF联接A", 2, 3, 1, 1),
    ("国泰中证全指通信设备ETF联接C", 2, 3, 1, 1),
    ("华夏恒生ETF联接A",            1, 2, 3, 1),
    ("华夏恒生ETF联接C",            1, 2, 3, 1),
    ("易方达恒生国企ETF联接A",       1, 1, 3, 1),
    ("易方达恒生国企ETF联接C",       1, 1, 3, 1),
    ("银华恒生中国企业ETF联接",      1, 2, 3, 1),
    ("易方达科创50ETF联接A",         3, 3, 1, 3),
    ("易方达科创50ETF联接C",         3, 3, 1, 3),
    ("广发创业板ETF联接A",           3, 3, 1, 3),
    ("广发创业板ETF联接C",           3, 3, 1, 3),
    ("天弘中证光伏ETF联接A",         3, 3, 1, 1),
    ("天弘中证光伏ETF联接C",         3, 3, 1, 1),
    ("国泰中证新能源汽车ETF联接A",   3, 3, 1, 1),
    ("国泰中证新能源汽车ETF联接C",   3, 3, 1, 1),
]


# ==================== 与现有 20 条人工打分的一致性 ====================


@pytest.mark.parametrize("基金简称,广度,波动,市场,板块", 基线20只)
def test_自动分类复现现有人工打分(基金简称, 广度, 波动, 市场, 板块):
    r = classify_fund(基金简称)
    assert (r["breadth"], r["volatility"], r["market"], r["board"]) == (广度, 波动, 市场, 板块)


def test_自动分类不产生待复核标记():
    """基线 20 只均在关键词规则覆盖内，不应触发人工复核。"""
    for 基金简称, *_ in 基线20只:
        assert classify_fund(基金简称)["needs_review"] is False


# ==================== 市场属性：QDII/跨境 ====================


@pytest.mark.parametrize("名称", [
    "华夏恒生ETF联接A", "易方达中概互联ETF联接A", "广发纳斯达克100ETF联接A",
    "博时标普500ETF联接A", "华安法国CAC40ETF联接A", "天弘越南市场ETF联接A",
])
def test_跨境名称_市场属性为3(名称):
    assert classify_fund(名称)["market"] == 3


def test_基金类型含海外_市场属性为3():
    """名称无线索时，靠移动端接口的基金类型兜底识别 QDII。"""
    assert classify_fund("某某指数基金A", ftype="指数型-海外股票")["market"] == 3


def test_纯A股基金_市场属性为1():
    assert classify_fund("易方达沪深300ETF联接A")["market"] == 1


# ==================== 板块特征：科创/创业 ====================


@pytest.mark.parametrize("名称", ["易方达科创50ETF联接A", "广发创业板ETF联接A", "华夏北证50ETF联接A"])
def test_科创创业北证_板块特征为3(名称):
    assert classify_fund(名称)["board"] == 3


def test_主板基金_板块特征为1():
    assert classify_fund("天弘中证银行ETF联接A")["board"] == 1


# ==================== 指数广度：主题(3) > 行业(2) > 宽基(1) ====================


@pytest.mark.parametrize("名称,期望", [
    ("易方达沪深300ETF联接A", 1),      # 宽基
    ("天弘中证银行ETF联接A", 2),       # 单一行业
    ("天弘中证光伏ETF联接A", 3),       # 窄基主题
])
def test_广度按主题行业宽基分档(名称, 期望):
    assert classify_fund(名称)["breadth"] == 期望


def test_主题优先于行业():
    """名称同时含行业词与主题词时，以更窄的主题为准。"""
    # "食品饮料"是行业、"消费电子"是主题
    assert classify_fund("某某中证消费电子ETF联接A")["breadth"] == 3


def test_行业优先于宽基():
    # "全指"命中宽基、"通信设备"命中行业，取更窄的行业
    assert classify_fund("国泰中证全指通信设备ETF联接A")["breadth"] == 2


# ==================== 波动属性：防御(1) > 成长(3) > 周期(2) ====================


@pytest.mark.parametrize("名称,期望", [
    ("天弘中证银行ETF联接A", 1),            # 防御
    ("天弘中证食品饮料ETF联接A", 2),        # 周期/消费
    ("国泰中证全指通信设备ETF联接A", 3),    # 高成长/TMT
])
def test_波动按防御周期成长分档(名称, 期望):
    assert classify_fund(名称)["volatility"] == 期望


def test_恒生中国企业不被误判为国企防御():
    """"恒生中**国企**业"含"国企"子串，但该指数是周期属性，不得命中防御规则。

    这是关键词子串匹配的经典陷阱：早期版本用通用词"国企"导致此处波动分
    从 2 误判为 1（与人工打分不符），故改为精确词"恒生国企"。
    """
    assert classify_fund("银华恒生中国企业ETF联接")["volatility"] == 2
    # 对照组：真正的恒生国企指数仍是防御
    assert classify_fund("易方达恒生国企ETF联接A")["volatility"] == 1


# ==================== 未命中规则时的兜底 ====================


def test_未知主题_给出保守兜底并标记复核():
    r = classify_fund("某某量子计算ETF联接A")
    assert r["breadth"] == 2
    assert r["volatility"] == 2
    assert r["needs_review"] is True


def test_未命中规则的基金仍产出可用等级():
    """needs_review 只是提示人工复核，不影响落库所需字段的完整性。"""
    r = classify_fund("某某量子计算ETF联接A")
    assert r["risk_level"] in ("moderate", "aggressive", "speculative")
    assert r["risk_label"] in ("中等风险", "较高风险", "高风险")


# ==================== 风险等级与标签 ====================


def test_四维分汇总为风险等级与中文标签():
    r = classify_fund("易方达科创50ETF联接A")  # 3+3+1+3=10
    assert r["risk_level"] == "speculative"
    assert r["risk_label"] == "高风险"


def test_低分基金为中等风险():
    r = classify_fund("易方达沪深300ETF联接A")  # 1+1+1+1=4
    assert r["risk_level"] == "moderate"
    assert r["risk_label"] == "中等风险"


def test_跟踪标的名称参与分类():
    """基金简称无线索时，用跟踪标的指数名补充判断。"""
    r = classify_fund("某某联接A", index_name="中证光伏产业指数")
    assert r["breadth"] == 3
