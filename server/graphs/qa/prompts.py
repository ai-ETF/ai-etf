"""
QA 分析图 LLM 提示词
"""


def get_qa_intent_prompt() -> str:
    """
    获取 QA 意图分类 Prompt（配合 tool calling 使用）

    Returns:
        意图分类 Prompt
    """
    return """你是一个金融领域的问题意图分类器。根据用户的问题，选择最合适的工具来分类。

工具说明：
- general_qa: 通用问题（无法归入其他类别的普通问题）
- comparison: 比较类问题（对比、差异、哪个好、vs、优劣、区别、选哪个）
- summary: 摘要总结类问题（总结、概括、概述、简要说明）
- trend: 趋势类问题（趋势、走向、未来、前景、预测、发展）
- factual_query: 事实查询类问题（净值、规模、费率、收益率、涨跌幅、具体数字）

请调用最匹配的工具。如果无法判断，调用 general_qa。"""


def get_qa_intent_fallback_prompt(question: str) -> str:
    """
    当 LLM tool calling 失败时，用自由文本方式让 LLM 分类

    Returns:
        自由文本分类 Prompt
    """
    return f"""请判断以下问题的意图类别，只输出类别名称（不要其他内容）：

可选类别：
- general: 通用问题
- comparison: 比较类问题
- summary: 摘要总结类问题
- trend: 趋势类问题
- factual_query: 事实查询类问题（净值、费率、规模等具体数字）

用户问题：{question}

类别："""
