"""
莱拉意图路由 Tools

定义各意图对应的 LangChain Tool，供 LLM 通过 tool calling 选择意图。
Tool 的 docstring 是 LLM 选择的依据。
"""
from langchain_core.tools import tool


@tool
def buy_decision(targets: str = "") -> str:
    """用户想买入、定投、抄底、选择 ETF 标的时使用。当用户提到"买"、"定投"、"抄底"、"选哪个"、"入手"、"配置"等词时调用此工具。"""
    return f"buy_decision: {targets}"


@tool
def position_manage(action: str = "") -> str:
    """用户已有持仓，想调整仓位时使用。当用户提到"加仓"、"减仓"、"持仓"、"仓位"、"补仓"、"调仓"等词时调用此工具。"""
    return f"position_manage: {action}"


@tool
def stop_loss(action: str = "") -> str:
    """用户想了解止盈止损策略时使用。当用户提到"止盈"、"止损"、"卖出"、"亏了"、"赚了要不要卖"等词时调用此工具。"""
    return f"stop_loss: {action}"


@tool
def knowledge_qa(question: str = "") -> str:
    """用户询问 ETF 基础知识、投资概念时使用。当用户提到"什么是"、"怎么理解"、"解释"、"区别"、"入门"等词时调用此工具。"""
    return f"knowledge_qa: {question}"


@tool
def market_analysis(topic: str = "") -> str:
    """用户想了解市场行情、政策解读时使用。当用户提到"行情"、"市场"、"政策"、"最近怎么样"、"今天涨跌"等词时调用此工具。"""
    return f"market_analysis: {topic}"


# 所有意图工具列表
INTENT_TOOLS = [
    buy_decision,
    position_manage,
    stop_loss,
    knowledge_qa,
    market_analysis,
]

# tool name → intent 映射
TOOL_NAME_TO_INTENT = {
    "buy_decision": "buy_decision",
    "position_manage": "position_manage",
    "stop_loss": "stop_loss",
    "knowledge_qa": "knowledge_qa",
    "market_analysis": "market_analysis",
}
