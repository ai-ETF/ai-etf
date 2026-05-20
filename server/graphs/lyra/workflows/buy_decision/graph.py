"""
买入决策 Skill 图编排

使用 LangGraph 编排买入决策工作流。
"""
import logging
from langgraph.graph import StateGraph, END

from server.graphs.lyra.workflows.buy_decision.state import (
    BuyDecisionSkillState,
    create_initial_buy_decision_state,
)
from server.graphs.lyra.workflows.buy_decision.nodes import (
    quick_response_node,
    intent_routing_node,
    output_brief_report_node,
    inquiry_chain_node,
    output_detail_report_node,
    decision_framework_node,
    generate_exec_plan_node,
)

logger = logging.getLogger(__name__)


def should_continue_inquiry(state: BuyDecisionSkillState) -> str:
    """
    判断是否继续追问

    Returns:
        "continue" - 继续追问
        "detail_report" - 输出详细报告
        "four_rules" - 进入四条纪律
        "exec_plan" - 生成执行计划
    """
    step = state.get("inquiry_step", 0)

    if state.get("skip_remaining_inquiry") or state.get("user_impatient"):
        return "detail_report"

    if step >= 5:
        # 追问完成，检查详细数据是否就绪
        return "detail_report"

    return "continue"


def route_after_brief(state: BuyDecisionSkillState) -> str:
    """
    简要报告后的路由

    Returns:
        "inquiry" - 开始追问链
        "end" - 结束（简单了解路径）
    """
    intent_route = state.get("intent_route", "deep")

    if intent_route == "simple":
        return "end"

    return "inquiry"


def build_buy_decision_skill_graph() -> StateGraph:
    """
    构建买入决策 Skill 图

    图结构：
        quick_response → intent_routing
            ├─ simple → output_brief → [END]
            └─ deep → output_brief → inquiry_chain → [条件边] → ...
    """
    graph = StateGraph(BuyDecisionSkillState)

    # 添加节点
    graph.add_node("quick_response", quick_response_node)
    graph.add_node("intent_routing", intent_routing_node)
    graph.add_node("output_brief", output_brief_report_node)
    graph.add_node("inquiry_chain", inquiry_chain_node)
    graph.add_node("output_detail", output_detail_report_node)
    graph.add_node("decision_framework", decision_framework_node)
    graph.add_node("generate_exec_plan", generate_exec_plan_node)

    # 设置入口点
    graph.set_entry_point("quick_response")

    # 添加边
    graph.add_edge("quick_response", "intent_routing")
    graph.add_edge("intent_routing", "output_brief")

    # 简要报告后条件路由
    graph.add_conditional_edges(
        "output_brief",
        route_after_brief,
        {
            "inquiry": "inquiry_chain",
            "end": END,
        },
    )

    # 追问链条件路由
    graph.add_conditional_edges(
        "inquiry_chain",
        should_continue_inquiry,
        {
            "continue": "inquiry_chain",  # 循环追问
            "detail_report": "output_detail",
            "four_rules": "inquiry_chain",  # 四条纪律在 inquiry_chain 中处理
            "exec_plan": "generate_exec_plan",
        },
    )

    # 详细报告后进入决策框架
    graph.add_edge("output_detail", "decision_framework")

    # 决策框架后生成执行计划
    graph.add_edge("decision_framework", "generate_exec_plan")

    # 执行计划生成后结束
    graph.add_edge("generate_exec_plan", END)

    return graph


# 全局图实例
_buy_decision_graph = None


def get_buy_decision_skill_graph():
    """获取买入决策 Skill 图单例"""
    global _buy_decision_graph
    if _buy_decision_graph is None:
        _buy_decision_graph = build_buy_decision_skill_graph().compile()
    return _buy_decision_graph
