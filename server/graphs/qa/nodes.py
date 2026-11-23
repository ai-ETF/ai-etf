"""
QA 分析图节点函数

实现意图分类和输出格式分析的核心节点。
"""
import logging
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage

from server.graphs.qa.state import QAState
from server.graphs.qa.prompts import get_qa_intent_prompt, get_qa_intent_fallback_prompt
from server.graphs.qa.tools import QA_INTENT_TOOLS, QA_TOOL_NAME_TO_INTENT
from server.llm import get_llm, get_llm_with_tools
from server.agents.question_agent import QuestionAgent  # 规则引擎
from server.agents.output_format_agent import OutputFormatAgent  # 格式映射

logger = logging.getLogger(__name__)

# 规则引擎实例（单例）
_rule_agent = None
_format_agent = None


def _get_rule_agent() -> QuestionAgent:
    """获取规则引擎单例"""
    global _rule_agent
    if _rule_agent is None:
        _rule_agent = QuestionAgent()
    return _rule_agent


def _get_format_agent() -> OutputFormatAgent:
    """获取格式分析引擎单例"""
    global _format_agent
    if _format_agent is None:
        _format_agent = OutputFormatAgent()
    return _format_agent


async def classify_intent_node(state: QAState) -> Dict[str, Any]:
    """
    意图分类节点

    流程：
    1. 规则快速通道：先用 QuestionAgent 的关键词匹配，高置信度直接返回
    2. LLM 路径：使用 tool calling 分类意图
    3. 兜底：如果 LLM 失败，返回规则引擎的结果

    Args:
        state: 当前状态

    Returns:
        状态更新字典：{intent, top_k}
    """
    question = state["question"]
    logger.debug(f"意图分类开始: question={question[:50]}...")

    # 1. 规则快速通道
    rule_agent = _get_rule_agent()
    rule_result = rule_agent.analyze(question)
    logger.debug(f"规则引擎结果: intent={rule_result.intent}, top_k={rule_result.top_k}")

    # 如果规则引擎置信度够高（comparison/factual_query 这类明确意图），直接使用
    if rule_result.intent in ("comparison", "factual_query"):
        logger.info(f"规则快速通道命中: intent={rule_result.intent}")
        return {
            "intent": rule_result.intent,
            "top_k": rule_result.top_k,
        }

    # 2. LLM tool calling 路径
    try:
        llm_with_tools = get_llm_with_tools(QA_INTENT_TOOLS)
        messages = [
            SystemMessage(content=get_qa_intent_prompt()),
            HumanMessage(content=question),
        ]

        response = await llm_with_tools.ainvoke(messages)

        # 解析 tool_calls
        if response.tool_calls:
            tool_name = response.tool_calls[0]["name"]
            intent = QA_TOOL_NAME_TO_INTENT.get(tool_name, "general")
            logger.info(f"LLM tool calling 结果: intent={intent}")
            return {
                "intent": intent,
                "top_k": _get_top_k_for_intent(intent),
            }

        # 没有调用工具，尝试自由文本解析
        content = response.content.strip().lower()
        if any(kw in content for kw in ["comparison", "比较", "对比"]):
            intent = "comparison"
        elif any(kw in content for kw in ["summary", "总结", "摘要"]):
            intent = "summary"
        elif any(kw in content for kw in ["trend", "趋势", "未来"]):
            intent = "trend"
        elif any(kw in content for kw in ["factual", "事实", "数字", "费率", "净值"]):
            intent = "factual_query"
        else:
            intent = "general"

        logger.info(f"LLM 自由文本解析: intent={intent}")
        return {
            "intent": intent,
            "top_k": _get_top_k_for_intent(intent),
        }

    except Exception as e:
        logger.warning(f"LLM 分类失败，降级到规则引擎: {e}")
        return {
            "intent": rule_result.intent,
            "top_k": rule_result.top_k,
        }


def _get_top_k_for_intent(intent: str) -> int:
    """根据意图返回 top_k 数量"""
    top_k_map = {
        "comparison": 8,    # 比较类需要更多上下文
        "factual_query": 3,
        "summary": 4,
        "trend": 6,
        "general": 5,
    }
    return top_k_map.get(intent, 5)


async def determine_format_node(state: QAState) -> Dict[str, Any]:
    """
    输出格式分析节点

    基于意图映射输出格式，复用 OutputFormatAgent 的规则逻辑。
    不需要调用 LLM，纯规则映射。

    Args:
        state: 当前状态

    Returns:
        状态更新字典：{output_format, format_analysis}
    """
    intent = state.get("intent", "general")
    logger.debug(f"格式分析开始: intent={intent}")

    format_agent = _get_format_agent()
    format_result = format_agent.analyze(intent=intent, content="", user_preference=None)

    logger.debug(f"格式分析结果: primary_format={format_result['primary_format']}")

    return {
        "output_format": format_result["primary_format"],
        "format_analysis": format_result,
    }