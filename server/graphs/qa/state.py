"""
QA 分析图状态定义

定义 QA 分析过程中各阶段的状态字段。
"""
from typing import TypedDict, Optional, Dict, Any


class QAState(TypedDict, total=False):
    """
    QA 分析状态

    输入：question
    输出：intent, output_format, top_k, format_analysis
    """
    # 输入
    question: str

    # 意图分类输出
    intent: str              # general, comparison, summary, trend, factual_query
    top_k: int               # 检索返回的文本块数量

    # 输出格式分析结果
    output_format: str       # text, table, bullet_points 等
    format_analysis: Optional[Dict[str, Any]]


def create_qa_state(question: str) -> QAState:
    """创建 QA 分析初始状态"""
    return QAState(
        question=question,
        intent="general",
        top_k=5,
        output_format="text",
        format_analysis=None,
    )
