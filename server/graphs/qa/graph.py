"""
QA 分析图编排

使用 LangGraph StateGraph 编排意图分类和输出格式分析节点。
"""
import logging
from typing import Dict, Any

from langgraph.graph import StateGraph, END

from server.graphs.qa.state import QAState, create_qa_state
from server.graphs.qa.nodes import classify_intent_node, determine_format_node

logger = logging.getLogger(__name__)

# 全局图实例
_qa_graph = None


def build_qa_graph() -> StateGraph:
    """
    构建 QA 分析图

    图结构:
        classify_intent → determine_format → END

    Returns:
        StateGraph 实例
    """
    graph = StateGraph(QAState)

    # 添加节点
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("determine_format", determine_format_node)

    # 设置入口点
    graph.set_entry_point("classify_intent")

    # 添加边
    graph.add_edge("classify_intent", "determine_format")
    graph.add_edge("determine_format", END)

    return graph


def get_qa_graph():
    """获取 QA 分析图单例"""
    global _qa_graph
    if _qa_graph is None:
        _qa_graph = build_qa_graph().compile()
    return _qa_graph


def run_qa_analysis(question: str) -> Dict[str, Any]:
    """
    运行 QA 分析图（同步接口）

    替代原有的 QuestionAgent.analyze() + OutputFormatAgent.analyze() 调用。

    Args:
        question: 用户问题

    Returns:
        包含意图、输出格式等分析结果的字典：
        {
            "intent": str,
            "output_format": str,
            "top_k": int,
            "format_analysis": dict,
        }
    """
    logger.debug(f"运行 QA 分析图: question={question[:50]}...")

    graph = get_qa_graph()
    initial_state = create_qa_state(question)

    # 使用 invoke（同步），LangGraph 会处理内部的 async 节点
    result = graph.invoke(initial_state)

    logger.debug(f"QA 分析完成: intent={result['intent']}, top_k={result['top_k']}")

    return {
        "intent": result.get("intent", "general"),
        "output_format": result.get("output_format", "text"),
        "top_k": result.get("top_k", 5),
        "format_analysis": result.get("format_analysis"),
    }