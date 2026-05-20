"""
莱拉主控 Agent 状态定义

定义 LyraState TypedDict，包含会话、意图、情绪、数据等所有状态字段。
"""
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from operator import add

from langchain_core.messages import BaseMessage


class DataStatus(TypedDict):
    """小研数据收集状态"""
    collection_id: str
    brief_ready: bool
    detail_ready: bool
    progress: str  # "0%", "50%", "100%"


class SkillState(TypedDict, total=False):
    """Skill 执行状态（通用字段，各 Skill 可扩展）"""
    # 当前执行步骤
    current_step: str
    # 步骤索引
    step_index: int
    # 用户回答汇总
    answers: Dict[str, Any]
    # Skill 特定数据
    extra: Dict[str, Any]


class LyraState(TypedDict):
    """
    莱拉主控 Agent 状态

    包含会话、意图识别、Skill 执行、数据、情绪检测、输出等所有字段。
    messages 使用 Annotated[List, add] 实现消息累加。
    """

    # ========== 会话 ==========
    session_id: str
    user_id: str
    # 消息历史（自动累加）
    messages: Annotated[List[BaseMessage], add]
    # 当前用户输入
    current_input: str

    # ========== 意图与路由 ==========
    # 意图类型：buy_decision, position_manage, stop_loss, knowledge_qa, market_analysis, unknown
    intent: Optional[str]
    # 意图置信度 (0-1)
    intent_confidence: float
    # 当前激活的 Skill 名称
    current_skill: Optional[str]

    # ========== Skill 执行状态 ==========
    # Skill 内部状态，由各 Skill 自行维护
    skill_state: SkillState

    # ========== 数据（来自小研） ==========
    # 数据收集状态
    data_status: DataStatus
    # 简要数据报告
    brief_data: Optional[Dict[str, Any]]
    # 详细数据报告
    detail_data: Optional[Dict[str, Any]]
    # 小研请求 ID
    xiaoyan_request_id: Optional[str]

    # ========== 情绪检测 ==========
    # 检测到的情绪标签：fomo, anxiety, regret, overconfidence
    emotion_flags: List[str]
    # 是否已完成情绪干预
    emotion_intervened: bool

    # ========== 输出 ==========
    # 莱拉的回复文本
    response: Optional[str]
    # 执行计划文档路径
    exec_plan_path: Optional[str]

    # ========== 控制流 ==========
    # 是否结束对话
    should_end: bool
    # 是否等待用户输入
    waiting_for_user: bool
    # 错误信息（如有）
    error: Optional[str]
    # interrupt 元数据（图暂停时设置）
    interrupt_metadata: Optional[Dict[str, Any]]


def create_initial_state(session_id: str, user_id: str, user_input: str) -> LyraState:
    """
    创建初始状态

    Args:
        session_id: 会话 ID
        user_id: 用户 ID
        user_input: 用户输入

    Returns:
        初始化的 LyraState
    """
    return LyraState(
        session_id=session_id,
        user_id=user_id,
        messages=[],
        current_input=user_input,
        intent=None,
        intent_confidence=0.0,
        current_skill=None,
        skill_state=SkillState(),
        data_status=DataStatus(
            collection_id="",
            brief_ready=False,
            detail_ready=False,
            progress="0%"
        ),
        brief_data=None,
        detail_data=None,
        xiaoyan_request_id=None,
        emotion_flags=[],
        emotion_intervened=False,
        response=None,
        exec_plan_path=None,
        should_end=False,
        waiting_for_user=False,
        error=None,
        interrupt_metadata=None,
    )
