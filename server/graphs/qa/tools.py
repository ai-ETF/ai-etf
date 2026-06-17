"""
QA 意图分类 Tools

定义各 QA 意图对应的 LangChain Tool，供 LLM 通过 tool calling 选择。
"""
from langchain_core.tools import tool


@tool
def general_qa(question: str = "") -> str:
    """通用问题。当问题无法归入比较、摘要、趋势或事实查询时使用。"""
    return f"general: {question}"


@tool
def comparison(targets: str = "") -> str:
    """比较类问题。当用户想对比、比较、看差异、选哪个、了解优劣时使用。包含"vs"、"哪个好"、"区别"、"比较"等关键词。"""
    return f"comparison: {targets}"


@tool
def summary(topic: str = "") -> str:
    """摘要总结类问题。当用户要求总结、概括、概述、简要说明时使用。"""
    return f"summary: {topic}"


@tool
def trend(topic: str = "") -> str:
    """趋势类问题。当用户问趋势、走向、未来、前景、预测、发展方向时使用。"""
    return f"trend: {topic}"


@tool
def factual_query(field: str = "") -> str:
    """事实查询类问题。当用户询问具体数字或数据时使用，如净值、规模、费率、收益率、涨跌幅。"""
    return f"factual_query: {field}"


# 所有 QA 意图工具列表
QA_INTENT_TOOLS = [
    general_qa,
    comparison,
    summary,
    trend,
    factual_query,
]

# tool name → intent 映射
QA_TOOL_NAME_TO_INTENT = {
    "general_qa": "general",
    "comparison": "comparison",
    "summary": "summary",
    "trend": "trend",
    "factual_query": "factual_query",
}
