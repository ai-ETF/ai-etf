"""
文档分析图编排

使用 LangGraph StateGraph 编排文档类型分类和结构分析节点。
"""
import logging
from typing import Dict, Any

from langgraph.graph import StateGraph, END

from server.graphs.document.state import DocumentState, create_document_state
from server.graphs.document.nodes import classify_document_type_node, analyze_structure_node

logger = logging.getLogger(__name__)

# 全局图实例
_document_graph = None


def build_document_graph() -> StateGraph:
    """
    构建文档分析图

    图结构:
        classify_document_type → analyze_structure → END

    Returns:
        StateGraph 实例
    """
    graph = StateGraph(DocumentState)

    # 添加节点
    graph.add_node("classify_document_type", classify_document_type_node)
    graph.add_node("analyze_structure", analyze_structure_node)

    # 设置入口点
    graph.set_entry_point("classify_document_type")

    # 添加边
    graph.add_edge("classify_document_type", "analyze_structure")
    graph.add_edge("analyze_structure", END)

    return graph


def get_document_graph():
    """获取文档分析图单例"""
    global _document_graph
    if _document_graph is None:
        _document_graph = build_document_graph().compile()
    return _document_graph


def run_document_analysis(content: str, doc_id: str = None) -> Dict[str, Any]:
    """
    运行文档分析图（同步接口）

    替代原有的 DocumentAgent.analyze() 调用。
    返回格式与 DocumentAgent.analyze() 完全一致，确保全链路兼容。

    Args:
        content: 文档内容
        doc_id: 文档 ID（可选）

    Returns:
        包含文档类型、结构等分析结果的字典：
        {
            "document_type": str,
            "key_info_locations": list,
            "content_structure": dict,
            "suggested_chunk_strategy": str,
            "confidence": float,
        }
    """
    logger.debug(f"运行文档分析图: content_length={len(content)}, doc_id={doc_id}")

    graph = get_document_graph()
    initial_state = create_document_state(content, doc_id)

    # 使用 invoke（同步），LangGraph 会处理内部的 async 节点
    result = graph.invoke(initial_state)

    logger.debug(f"文档分析完成: type={result.get('document_type')}, confidence={result.get('confidence'):.2f}")

    return {
        "document_type": result.get("document_type", "general_document"),
        "key_info_locations": result.get("key_info_locations", []),
        "content_structure": result.get("content_structure", {}),
        "suggested_chunk_strategy": result.get("suggested_chunk_strategy", "按自然段落分块"),
        "confidence": result.get("confidence", 0.5),
    }
