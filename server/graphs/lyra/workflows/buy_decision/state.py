"""
买入决策 Skill 状态定义

继承莱拉状态的核心字段，新增买入决策专用状态。
"""
from typing import TypedDict, Optional, List, Dict, Any


class InquiryAnswers(TypedDict, total=False):
    """追问链用户回答"""
    # Q1: 投资目标
    goal: str
    goal_detail: str  # "估值低想配置消费板块" / "看到别人赚了" 等
    # Q2: 投资期限
    horizon: str
    is_idle_money: bool  # 是否闲钱
    # Q3: 风险认知
    risk_tolerance: str  # weak / medium / strong
    risk_behavior: str  # sell / add / hold / uncertain
    # Q4: 自我匹配
    self_match_response: str


class PostBuyRules(TypedDict, total=False):
    """四条纪律"""
    # 1. 买入逻辑锚点
    logic_anchor: Dict[str, Any]
    # 2. 风险底线
    risk_bottom_line: Dict[str, Any]
    # 3. 止盈策略
    take_profit: Dict[str, Any]
    # 4. 补仓规则
    add_position: Dict[str, Any]


class BuyDecisionSkillState(TypedDict, total=False):
    """
    买入决策 Skill 状态

    该状态作为 LyraState.skill_state["extra"] 中 buy_decision 子键的值。
    """

    # ========== 标的 ==========
    # 对比的标的列表，如 ["消费50", "消费80"]
    targets: List[str]

    # ========== 意图分流 ==========
    # simple（简单了解）或 deep（深入分析）
    intent_route: str

    # ========== 追问链 ==========
    # 当前追问步骤 (0=未开始, 1=投资目标, 2=投资期限, 3=标的理解, 4=风险认知, 5=自我匹配, 6=四条纪律)
    inquiry_step: int
    # 用户回答
    inquiry_answers: InquiryAnswers
    # 标的理解是否已输出
    target_understanding_given: bool
    # 四条纪律
    post_buy_rules: PostBuyRules

    # ========== 决策结果 ==========
    # 用户选择的标的
    selected_target: Optional[str]
    # 仓位大小
    position_size: Optional[str]
    # 建仓方式
    build_method: Optional[str]  # "一次性" / "分批定投"
    # 入场时机
    timing: Optional[str]
    # 决整理由
    decision_reason: Optional[str]

    # ========== 控制标志 ==========
    # 是否跳过剩余追问
    skip_remaining_inquiry: bool
    # 用户是否不耐烦
    user_impatient: bool


def create_initial_buy_decision_state() -> BuyDecisionSkillState:
    """创建买入决策初始状态"""
    return BuyDecisionSkillState(
        targets=[],
        intent_route="deep",
        inquiry_step=0,
        inquiry_answers=InquiryAnswers(),
        target_understanding_given=False,
        post_buy_rules=PostBuyRules(),
        selected_target=None,
        position_size=None,
        build_method=None,
        timing=None,
        decision_reason=None,
        skip_remaining_inquiry=False,
        user_impatient=False,
    )
