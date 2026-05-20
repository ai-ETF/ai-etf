"""
小研数据收集节点

实现数据收集、整合、报告生成的各节点函数。
"""
import asyncio
import logging
import uuid
from typing import Dict, Any, List

from server.graphs.xiaoyan.state import (
    XiaoYanState,
    create_xiaoyan_state,
)
from server.graphs.xiaoyan.sources.akshare_client import get_akshare_client
from server.graphs.xiaoyan.sources.rag_client import get_rag_client

logger = logging.getLogger(__name__)


async def parse_request_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    解析数据请求

    提取 targets 和 data_requirements，初始化收集状态。
    """
    logger.info(f"解析数据请求: targets={state['targets']}")

    return {
        "status": "collecting",
        "progress": 0.0,
        "errors": [],
    }


async def health_check_sources_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    检查各数据源健康状态
    """
    akshare = get_akshare_client()
    rag = get_rag_client()

    akshare_health = await akshare.health_check()
    rag_health = await rag.health_check()

    return {
        "source_status": {
            "python_lib": akshare_health.get("status", "unknown"),
            "rag": rag_health.get("status", "unknown"),
            "web_search": "unknown",  # 暂未实现
        },
        "progress": 5.0,
    }


async def collect_valuation_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    收集估值数据
    """
    akshare = get_akshare_client()
    targets = state["targets"]

    valuation_data = {}

    for symbol in targets:
        try:
            data = await akshare.get_etf_valuation(symbol)
            valuation_data[symbol] = data
        except Exception as e:
            logger.error(f"收集估值数据失败 {symbol}: {e}")

    return {
        "valuation_data": valuation_data,
        "progress": 20.0,
    }


async def collect_fund_flow_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    收集资金流向数据
    """
    akshare = get_akshare_client()
    targets = state["targets"]

    fund_flow_data = {}

    for symbol in targets:
        try:
            data = await akshare.get_etf_fund_flow(symbol, days=30)
            fund_flow_data[symbol] = data
        except Exception as e:
            logger.error(f"收集资金流向失败 {symbol}: {e}")

    return {
        "fund_flow_data": fund_flow_data,
        "progress": 35.0,
    }


async def collect_composition_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    收集成分股数据
    """
    akshare = get_akshare_client()
    targets = state["targets"]

    composition_data = {}

    for symbol in targets:
        try:
            data = await akshare.get_etf_composition(symbol)
            composition_data[symbol] = data
        except Exception as e:
            logger.error(f"收集成分股失败 {symbol}: {e}")

    return {
        "composition_data": composition_data,
        "progress": 50.0,
    }


async def collect_rag_views_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    从 RAG 知识库收集投行观点
    """
    rag = get_rag_client()
    targets = state["targets"]

    institution_views = []
    bull_views = []
    bear_views = []

    try:
        # 查询投行观点
        institution_views = await rag.query_institution_views(targets)

        # 查询看多看空观点
        for target in targets:
            views = await rag.query_bull_bear_views(target)
            bull_views.extend(views.get("bull", []))
            bear_views.extend(views.get("bear", []))

    except Exception as e:
        logger.error(f"收集 RAG 观点失败: {e}")
        state["errors"].append(f"RAG 查询失败: {e}")

    return {
        "institution_views": institution_views,
        "bull_views": bull_views,
        "bear_views": bear_views,
        "progress": 70.0,
    }


async def integrate_data_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    整合数据

    去重、校验、格式化
    """
    # 数据整合逻辑
    # 目前主要是传递，后续可添加校验和去重

    has_data = (
        state.get("valuation_data") or
        state.get("fund_flow_data") or
        state.get("institution_views")
    )

    return {
        "progress": 80.0,
        "partial_data_available": bool(has_data),
    }


async def generate_brief_report_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    生成简要数据报告

    包含：估值概览、资金流向、市场观点一句话
    """
    targets = state["targets"]
    valuation_data = state.get("valuation_data", {})
    fund_flow_data = state.get("fund_flow_data", {})

    # 构建简要报告
    comparison = {}

    for target in targets:
        target_data = {}

        # 估值
        if target in valuation_data:
            val = valuation_data[target]
            target_data["valuation"] = {
                "pe": val.get("pe"),
                "pe_percentile": val.get("pe_percentile"),
                "interpretation": val.get("interpretation", ""),
            }

        # 资金流向
        if target in fund_flow_data:
            flow = fund_flow_data[target]
            target_data["fund_flow"] = {
                "net_flow": flow.get("net_flow"),
                "trend": flow.get("trend"),
                "interpretation": flow.get("interpretation", ""),
            }

        comparison[target] = target_data

    # 市场观点摘要
    market_view = "暂无市场观点数据"
    institution_views = state.get("institution_views", [])
    if institution_views:
        # 简单汇总
        market_view = f"共获取到 {len(institution_views)} 条投行观点"

    brief_report = {
        "targets": targets,
        "comparison": comparison,
        "market_view_summary": market_view,
    }

    return {
        "brief_report": brief_report,
        "status": "brief_ready",
        "progress": 90.0,
    }


async def generate_detail_report_node(state: XiaoYanState) -> Dict[str, Any]:
    """
    生成详细数据报告

    包含：完整估值、基本面、正反观点、投行观点、风险提示
    """
    targets = state["targets"]

    detail_report = {
        "targets": targets,
        "valuation": state.get("valuation_data", {}),
        "fund_flow": state.get("fund_flow_data", {}),
        "composition": state.get("composition_data", {}),
        "bull_views": state.get("bull_views", []),
        "bear_views": state.get("bear_views", []),
        "institution_views": state.get("institution_views", []),
        "policy_events": [],  # 暂未实现联网搜索
        "risk_warnings": [
            "历史数据不代表未来表现",
            "估值低不等于不会继续跌",
            "投行观点仅供参考，不构成投资建议",
        ],
    }

    return {
        "detail_report": detail_report,
        "status": "detail_ready",
        "progress": 100.0,
    }


# ========== 辅助函数 ==========

def create_xiaoyan_request(
    targets: List[str],
    data_requirements: Dict[str, List[str]],
) -> XiaoYanState:
    """
    创建小研数据请求

    Args:
        targets: 标的列表
        data_requirements: 数据需求 {"brief": [...], "detail": [...]}

    Returns:
        初始化的 XiaoYanState
    """
    request_id = str(uuid.uuid4())
    return create_xiaoyan_state(
        request_id=request_id,
        targets=targets,
        data_requirements=data_requirements,
    )
