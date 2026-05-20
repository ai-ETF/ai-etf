"""
莱拉主控图编排

使用 LangGraph StateGraph 编排各节点和边，构建莱拉的主控流程。
"""
import logging
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from server.graphs.lyra.state import LyraState, create_initial_state
from server.graphs.lyra.nodes import (
    entry_node,
    check_emotion_node,
    emotion_intervention_node,
    classify_intent_node,
    output_node,
    save_state_node,
    route_to_skill_node,
)
from server.graphs.lyra.edges import (
    should_intervene_emotion,
    route_by_intent,
    should_end,
    route_skill_output,
)

logger = logging.getLogger(__name__)


def build_lyra_graph() -> StateGraph:
    """
    构建莱拉主控图

    图结构:
        entry → check_emotion → [emotion_intervention?] → classify_intent
            → route_by_intent → [buy_decision_skill] → output → save_state → [END/继续]

    Returns:
        编译后的 StateGraph
    """
    # 创建图
    graph = StateGraph(LyraState)

    # 添加节点
    graph.add_node("entry", entry_node)
    graph.add_node("check_emotion", check_emotion_node)
    graph.add_node("emotion_intervention", emotion_intervention_node)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("buy_decision_skill", _buy_decision_skill_placeholder)
    graph.add_node("output", output_node)
    graph.add_node("save_state", save_state_node)

    # 设置入口点
    graph.set_entry_point("entry")

    # 添加边
    graph.add_edge("entry", "check_emotion")

    # 情绪检测条件边
    graph.add_conditional_edges(
        "check_emotion",
        should_intervene_emotion,
        {
            "emotion_intervention": "emotion_intervention",
            "classify_intent": "classify_intent",
        },
    )

    # 情绪干预后继续意图分类
    graph.add_edge("emotion_intervention", "classify_intent")

    # 意图分类条件边
    graph.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "buy_decision_skill": "buy_decision_skill",
            "output": "output",
        },
    )

    # Skill 执行后输出
    graph.add_edge("buy_decision_skill", "output")

    # 输出后保存状态
    graph.add_edge("output", "save_state")

    # 保存状态后判断是否结束
    graph.add_conditional_edges(
        "save_state",
        should_end,
        {
            "end": END,
            "continue": "entry",  # 多轮对话继续
        },
    )

    return graph


async def _buy_decision_skill_placeholder(state: LyraState) -> dict:
    """
    TODO 买入决策 Skill 占位节点

    MVP 阶段使用简化实现，后续替换为完整的 Skill 子图。
    """
    from server.graphs.lyra.prompts import get_system_prompt

    user_input = state.get("current_input", "")

    # 简单实现： 使用 Skill 内容生成回复
    from server.skills.registry import get_skill_registry
    from server.skills.loader import SkillLoader

    registry = get_skill_registry()
    skill_metadata = registry.get_skill("buy-decision")

    if skill_metadata:
        loader = SkillLoader(skill_metadata.path)
        skill_content = loader.load_full_skill()

        # 使用 LLM 生成回复
        from langchain_core.messages import SystemMessage, HumanMessage
        from server.llm import get_llm

        try:
            llm = get_llm()

            messages = [
                SystemMessage(content=get_system_prompt()),
                SystemMessage(content=f"# 买入决策 Skill 指令\n\n{skill_content}"),
                HumanMessage(content=user_input),
            ]

            response = await llm.ainvoke(messages)
            response_text = response.content

            return {"response": response_text, "should_end": True}

        except Exception as e:
            logger.error(f"买入决策 Skill 执行失败: {e}")
            return {
                "response": "抱歉，我暂时无法处理这个问题。请稍后再试。",
                "error": str(e),
            }

    return {"response": "我正在学习如何帮你做买入决策分析。"}


# 全局图实例
_lyra_graph = None


def get_lyra_graph():
    """获取莱拉图单例"""
    global _lyra_graph
    if _lyra_graph is None:
        _lyra_graph = build_lyra_graph().compile(
            checkpointer=MemorySaver()
        )
    return _lyra_graph


async def run_lyra(
    user_id: str,
    session_id: str,
    user_input: str,
) -> dict:
    """
    运行莱拉图

    支持 interrupt/resume 模式：
    - 如果有 pending interrupt（追问链等待用户回答），用 Command(resume=user_input) 恢复
    - 否则正常创建初始状态并执行

    Args:
        user_id: 用户 ID
        session_id: 会话 ID
        user_input: 用户输入

    Returns:
        最终状态 dict，额外包含 _interrupted 和 _waiting_for_input 字段
    """
    graph = get_lyra_graph()

    # 配置
    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    # 检查是否有 pending interrupt（图暂停在某个节点等待用户输入）
    snapshot = await graph.aget_state(config)

    if snapshot.next:
        # 有节点在等待 — 用 Command(resume=...) 恢复执行
        logger.info(f"恢复 interrupt: session_id={session_id}, resume={user_input[:50]}...")
        result = await graph.ainvoke(
            Command(resume=user_input),
            config=config,
        )
    else:
        # 正常执行：创建初始状态并运行
        initial_state = create_initial_state(
            session_id=session_id,
            user_id=user_id,
            user_input=user_input,
        )
        result = await graph.ainvoke(initial_state, config=config)

    # 检查执行后是否有新的 interrupt
    post_snapshot = await graph.aget_state(config)
    result["_interrupted"] = bool(post_snapshot.next)
    result["_waiting_for_input"] = bool(post_snapshot.next)

    return result
