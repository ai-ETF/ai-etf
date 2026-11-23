"""
文档类型分类 Tools

定义各文档类型对应的 LangChain Tool，供 LLM 通过 tool calling 选择。
"""
from langchain_core.tools import tool


@tool
def financial_report(summary: str = "") -> str:
    """财务报告。包含资产负债表、利润表、现金流量表、净利润、营业收入、总资产、股东权益等财务数据。"""
    return f"financial_report: {summary}"


@tool
def etf_report(summary: str = "") -> str:
    """ETF/基金报告。包含基金、ETF、净值、持仓、重仓股、招募说明书、基金合同、投资策略、风险提示等内容。"""
    return f"etf_report: {summary}"


@tool
def news_article(summary: str = "") -> str:
    """新闻报道。包含新闻、报道、消息、采访、事件、市场评论、观点分析等内容。"""
    return f"news_article: {summary}"


@tool
def regulatory_document(summary: str = "") -> str:
    """法规/监管文件。包含法规、监管、政策、通知、规定、办法、指导意见、合规要求等内容。"""
    return f"regulatory_document: {summary}"


@tool
def general_document(summary: str = "") -> str:
    """通用文档。无法归入财务报告、ETF报告、新闻、法规类别的文档。"""
    return f"general_document: {summary}"


# 所有文档类型工具列表
DOC_TYPE_TOOLS = [
    financial_report,
    etf_report,
    news_article,
    regulatory_document,
    general_document,
]

# tool name → document type 映射
DOC_TOOL_NAME_TO_TYPE = {
    "financial_report": "financial_report",
    "etf_report": "etf_report",
    "news_article": "news_article",
    "regulatory_document": "regulatory_document",
    "general_document": "general_document",
}
