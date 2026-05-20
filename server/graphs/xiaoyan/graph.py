"""
小研数据收集图

使用 LangGraph StateGraph 编排数据收集流程。
作为独立图运行，由莱拉异步触发。
"""
import logging
from typing import Dict, Any

from langgraph.graph import StateGraph, END

from server.graphs.xiaoyan.state import XiaoYanState
from server.graphs.xiaoyan.nodes import (
    parse_request_node,
    health_check_sources_node,
    collect_valuation_node,
    collect_fund_flow_node,
    collect_composition_node,
    collect_rag_views_node,
    integrate_data_node,
    generate_brief_report_node,
    generate_detail_report_node,
    create_xiaoyan_request,
)

logger = logging.getLogger(__name__)


def build_xiaoyan_graph() -> StateGraph:
    """
    构建小研数据收集图

    流程：
    parse_request → health_check → collect_valuation + collect_fund_flow + collect_composition + collect_rag
                   → integrate → generate_brief → generate_detail → END
    """
    graph = StateGraph(XiaoYanState)

    # 添加节点
    graph.add_node("parse_request", parse_request_node)
    graph.add_node("health_check", health_check_sources_node)
    graph.add_node("collect_valuation", collect_valuation_node)
    graph.add_node("collect_fund_flow", collect_fund_flow_node)
    graph.add_node("collect_composition", collect_composition_node)
    graph.add_node("collect_rag_views", collect_rag_views_node)
    graph.add_node("integrate", integrate_data_node)
    graph.add_node("generate_brief", generate_brief_report_node)
    graph.add_node("generate_detail", generate_detail_report_node)

    # 入口
    graph.set_entry_point("parse_request")

    # 顺序执行（数据收集可优化为并行，但 MVP 先用顺序）
    graph.add_edge("parse_request", "health_check")
    graph.add_edge("health_check", "collect_valuation")
    graph.add_edge("collect_valuation", "collect_fund_flow")
    graph.add_edge("collect_fund_flow", "collect_composition")
    graph.add_edge("collect_composition", "collect_rag_views")
    graph.add_edge("collect_rag_views", "integrate")
    graph.add_edge("integrate", "generate_brief")
    graph.add_edge("generate_brief", "generate_detail")
    graph.add_edge("generate_detail", END)

    return graph.compile()


# 全局图实例
_graph = None


def get_xiaoyan_graph() -> StateGraph:
    """获取小研数据收集图单例"""
    global _graph
    if _graph is None:
        _graph = build_xiaoyan_graph()
    return _graph


async def run_xiaoyan_async(
    targets: list[str],
    data_requirements: dict[str, list[str]],
) -> dict[str, Any]:
    """
    异步运行小研数据收集

    由莱拉的 entry 节点调用，在后台执行。

    Args:
        targets: 标的列表
        data_requirements: 数据需求

    Returns:
        最终状态（包含 brief_report 和 detail_report）
    """
    initial_state = create_xiaoyan_request(targets, data_requirements)
    graph = get_xiaoyan_graph()

    logger.info(f"小研开始收集数据: targets={targets}")

    try:
        # 运行图
        final_state = await graph.ainvoke(initial_state)

        logger.info(
            f"小研数据收集完成: status={final_state.get('status')}, "
            f"progress={final_state.get('progress')}%"
        )

        return dict(final_state)

    except Exception as e:
        logger.error(f"小研数据收集失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "brief_report": None,
            "detail_report": None,
        }
