"""
文档分析图 LLM 提示词
"""


def get_document_type_prompt() -> str:
    """
    获取文档类型分类 Prompt（配合 tool calling 使用）

    Returns:
        文档类型分类 Prompt
    """
    return """你是一个文档类型分类器。根据提供的文档内容，选择最合适的工具来分类。

工具说明：
- financial_report: 财务报告（包含资产负债表、利润表、现金流量表、净利润、营业收入、财务状况等）
- etf_report: ETF/基金报告（包含基金、净值、持仓、招募说明书、基金合同、投资策略等）
- news_article: 新闻报道（包含新闻、报道、市场评论、观点分析等）
- regulatory_document: 法规/监管文件（包含法规、政策、通知、规定、监管要求等）
- general_document: 通用文档（无法归入以上类别的文档）

请调用最匹配的工具。"""


def get_document_type_fallback_prompt(content_preview: str) -> str:
    """
    当 LLM tool calling 失败时，用自由文本方式分类

    Returns:
        自由文本分类 Prompt
    """
    return f"""请判断以下文档内容的类型，只输出类型名称（不要其他内容）：

可选类型：
- financial_report: 财务报告
- etf_report: ETF/基金报告
- news_article: 新闻报道
- regulatory_document: 法规/监管文件
- general_document: 通用文档

文档内容预览（前500字）：
{content_preview}

类型："""
