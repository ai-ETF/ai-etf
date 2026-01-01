from dataclasses import dataclass
from typing import Optional


@dataclass
class DecisionResult:
    """
    决策结果数据类
    用于存储问题分析的决策结果，包括意图、输出格式、返回数量等信息
    """
    intent: str  # 问题意图（general, comparison, summary, trend）
    output_format: str  # 输出格式（text, table等）
    top_k: int  # 返回的文本块数量
    doc_filter: Optional[str] = None  # 文档过滤器（可选）