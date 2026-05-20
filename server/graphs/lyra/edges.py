"""
莱拉主控图条件边

定义各节点之间的路由逻辑。
"""
from typing import Literal
from server.graphs.lyra.state import LyraState


def should_intervene_emotion(state: LyraState) -> Literal["emotion_intervention", "classify_intent"]:
    """
    检查是否需要情绪干预

    如果检测到情绪信号且尚未干预，则路由到情绪干预节点。
    """
    emotion_flags = state.get("emotion_flags", [])
    emotion_intervened = state.get("emotion_intervened", False)

    if emotion_flags and not emotion_intervened:
        return "emotion_intervention"

    return "classify_intent"


def route_by_intent(state: LyraState) -> Literal["buy_decision_skill", "output"]:
    """
    根据意图路由到对应的 Skill 或输出节点

    MVP 阶段只支持 buy_decision，其他意图走兜底输出。
    """
    intent = state.get("intent", "unknown")
    intent_confidence = state.get("intent_confidence", 0)

    # 置信度阈值
    if intent_confidence < 0.5:
        return "output"

    if intent == "buy_decision":
        return "buy_decision_skill"

    # 其他意图暂不支持，走兜底
    return "output"


def check_data_ready(state: LyraState) -> Literal["proceed", "wait_for_data"]:
    """
    检查数据是否就绪

    根据当前 Skill 的数据需求检查小研的数据收集状态。
    """
    current_skill = state.get("current_skill")
    data_status = state.get("data_status", {})

    if current_skill == "buy_decision":
        # 买入决策需要简要数据
        if data_status.get("brief_ready"):
            return "proceed"
        return "wait_for_data"

    # 其他 Skill 暂时默认为数据就绪
    return "proceed"


def should_end(state: LyraState) -> Literal["end", "continue"]:
    """
    判断对话是否应该结束

    - should_end=True → 结束
    - 否则继续（多轮对话回到 entry）
    """
    if state.get("should_end"):
        return "end"

    return "continue"


def route_skill_output(state: LyraState) -> Literal["save_state", "continue_skill"]:
    """
    判断 Skill 是否执行完毕

    如果 Skill 生成了响应，则保存状态并输出。
    """
    response = state.get("response")

    if response:
        return "save_state"

    return "continue_skill"
