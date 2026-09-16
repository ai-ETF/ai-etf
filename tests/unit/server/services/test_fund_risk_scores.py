"""fund_risk_scores 单元测试：基金/用户风险等级计算与标签映射。

模块名称：server/services/fund_risk_scores.py
所测功能：calc_risk_level（四维总分 → 风险等级）、get_risk_label（基金风险等级 → 中文标签）、
         get_user_risk_label（用户风险等级 → 中文标签）
测试方法：纯函数直测，无外部依赖，全程不联网、不连 Supabase。

阈值口径（SCORE_THRESHOLDS）：总分 ≤5 → moderate，≤7 → aggressive，>7 → speculative。
"""
from server.services.fund_risk_scores import (
    calc_risk_level,
    get_risk_label,
    get_user_risk_label,
)


# ==================== calc_risk_level：四维总分 → 等级 ====================


def test_总分4_最低分_为moderate():
    assert calc_risk_level(breadth=1, volatility=1, market=1, board=1) == "moderate"


def test_总分5_恰好等于阈值_为moderate():
    assert calc_risk_level(breadth=2, volatility=1, market=1, board=1) == "moderate"


def test_总分6_越过5阈值_为aggressive():
    assert calc_risk_level(breadth=2, volatility=2, market=1, board=1) == "aggressive"


def test_总分7_恰好等于阈值_为aggressive():
    assert calc_risk_level(breadth=2, volatility=2, market=2, board=1) == "aggressive"


def test_总分8_越过7阈值_为speculative():
    assert calc_risk_level(breadth=2, volatility=2, market=2, board=2) == "speculative"


def test_总分12_最高分_为speculative():
    assert calc_risk_level(breadth=3, volatility=3, market=3, board=3) == "speculative"


# ==================== get_risk_label：基金等级 → 中文标签 ====================


def test_基金等级moderate_映射中等风险():
    assert get_risk_label("moderate") == "中等风险"


def test_基金等级aggressive_映射较高风险():
    assert get_risk_label("aggressive") == "较高风险"


def test_基金等级speculative_映射高风险():
    assert get_risk_label("speculative") == "高风险"


def test_未知基金等级_原样返回():
    assert get_risk_label("unknown") == "unknown"


# ==================== get_user_risk_label：用户等级 → 中文标签 ====================


def test_用户等级conservative_映射保守型():
    assert get_user_risk_label("conservative") == "保守型"


def test_用户等级moderate_映射稳健型():
    assert get_user_risk_label("moderate") == "稳健型"


def test_用户等级aggressive_映射进取型():
    assert get_user_risk_label("aggressive") == "进取型"


def test_未知用户等级_原样返回():
    assert get_user_risk_label("unknown") == "unknown"
