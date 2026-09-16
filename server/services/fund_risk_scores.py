"""
基金风险等级计算（纯工具模块，不存储基金数据）

规则见 docs/基金风险等级划分设计文档.md

使用方式：
    from server.services.fund_risk_scores import calc_risk_level, get_risk_label

    level = calc_risk_level(breadth=1, volatility=1, market=1, board=1)  # "moderate"
    label = get_risk_label(level)                                         # "中等风险"
"""

# ==================== 常量 ====================

# 总分 → 等级映射（按阈值从小到大排列）
SCORE_THRESHOLDS = [
    (5, "moderate"),                     # ≤5
    (7, "aggressive"),                   # ≤7
    (float("inf"), "speculative"),       # >7
]

RISK_LABELS = {
    "moderate":    "中等风险",
    "aggressive":  "较高风险",
    "speculative": "高风险",
}

USER_RISK_LABELS = {
    "conservative": "保守型",
    "moderate":     "稳健型",
    "aggressive":   "进取型",
}


# ==================== 纯函数 ====================

def calc_risk_level(*, breadth: int, volatility: int,
                    market: int, board: int) -> str:
    """
    纯函数：四维得分 → 风险等级。

    参数:
        breadth:    指数广度 (1/2/3)
        volatility: 波动属性 (1/2/3)
        market:     市场属性 (1=纯A股, 3=QDII)
        board:      板块特征 (1=主板, 3=科创/创业)

    返回:
        risk_level: "moderate" / "aggressive" / "speculative"
    """
    total = breadth + volatility + market + board
    for threshold, level in SCORE_THRESHOLDS:
        if total <= threshold:
            return level
    return "speculative"


def get_risk_label(risk_level: str) -> str:
    """风险等级 → 中文标签"""
    return RISK_LABELS.get(risk_level, risk_level)


def get_user_risk_label(user_risk_level: str) -> str:
    """用户风险等级 → 中文标签"""
    return USER_RISK_LABELS.get(user_risk_level, user_risk_level)
