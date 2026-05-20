"""
小研数据收集 Agent 状态定义

定义数据收集过程中的所有状态字段。
"""
from typing import TypedDict, Optional, List, Dict, Any


class DataSourceStatus(TypedDict):
    """数据源运行状态"""
    python_lib: str  # ok / degraded / down
    rag: str         # ok / degraded / down
    web_search: str  # ok / degraded / down


class XiaoYanState(TypedDict):
    """
    小研数据收集状态

    独立于莱拉状态，异步运行，通过 data_status 与莱拉同步。
    """

    # ========== 请求 ==========
    # 请求 ID（由莱拉生成）
    request_id: str
    # 目标标的列表
    targets: List[str]
    # 数据需求
    data_requirements: Dict[str, List[str]]

    # ========== 收集状态 ==========
    # 当前状态：collecting / brief_ready / detail_ready / failed
    status: str
    # 收集进度 (0-100)
    progress: float

    # ========== 数据源状态 ==========
    source_status: DataSourceStatus

    # ========== 已收集数据 ==========
    # 估值数据
    valuation_data: Optional[Dict[str, Any]]
    # 基本面数据
    fundamental_data: Optional[Dict[str, Any]]
    # 资金流向数据
    fund_flow_data: Optional[Dict[str, Any]]
    # 成分股/权重数据
    composition_data: Optional[Dict[str, Any]]
    # 投行观点
    institution_views: Optional[List[Dict[str, Any]]]
    # 看多观点
    bull_views: Optional[List[Dict[str, Any]]]
    # 看空观点
    bear_views: Optional[List[Dict[str, Any]]]
    # 政策事件
    policy_events: Optional[List[Dict[str, Any]]]

    # ========== 输出报告 ==========
    # 简要数据报告
    brief_report: Optional[Dict[str, Any]]
    # 详细数据报告
    detail_report: Optional[Dict[str, Any]]

    # ========== 错误处理 ==========
    errors: List[str]
    # 是否有部分数据可用
    partial_data_available: bool


def create_xiaoyan_state(
    request_id: str,
    targets: List[str],
    data_requirements: Dict[str, List[str]],
) -> XiaoYanState:
    """创建小研初始状态"""
    return XiaoYanState(
        request_id=request_id,
        targets=targets,
        data_requirements=data_requirements,
        status="collecting",
        progress=0.0,
        source_status=DataSourceStatus(
            python_lib="unknown",
            rag="unknown",
            web_search="unknown",
        ),
        valuation_data=None,
        fundamental_data=None,
        fund_flow_data=None,
        composition_data=None,
        institution_views=None,
        bull_views=None,
        bear_views=None,
        policy_events=None,
        brief_report=None,
        detail_report=None,
        errors=[],
        partial_data_available=False,
    )
