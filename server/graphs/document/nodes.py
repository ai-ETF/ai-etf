"""
文档分析图节点函数

实现文档类型分类和结构分析的核心节点。
"""
import re
import logging
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage

from server.graphs.document.state import DocumentState
from server.graphs.document.prompts import get_document_type_prompt, get_document_type_fallback_prompt
from server.graphs.document.tools import DOC_TYPE_TOOLS, DOC_TOOL_NAME_TO_TYPE
from server.llm import get_llm, get_llm_with_tools
from server.agents.document_agent import DocumentAgent  # 规则引擎

logger = logging.getLogger(__name__)

# 规则引擎实例（单例）
_rule_doc_agent = None


def _get_rule_agent() -> DocumentAgent:
    """获取规则引擎单例"""
    global _rule_doc_agent
    if _rule_doc_agent is None:
        _rule_doc_agent = DocumentAgent()
    return _rule_doc_agent


async def classify_document_type_node(state: DocumentState) -> Dict[str, Any]:
    """
    文档类型分类节点

    流程：
    1. 规则快速通道：先用 DocumentAgent 的关键词匹配，高置信度直接返回
    2. LLM 路径：使用 tool calling 分类文档类型
    3. 兜底：如果 LLM 失败，返回规则引擎的结果

    Args:
        state: 当前状态

    Returns:
        状态更新字典：{document_type, confidence}
    """
    content = state["content"]
    logger.debug(f"文档类型分类开始，内容长度: {len(content)}")

    # 1. 规则快速通道
    rule_agent = _get_rule_agent()
    rule_result = rule_agent.analyze(content, doc_id=state.get("doc_id"))
    rule_doc_type = rule_result["document_type"]
    rule_confidence = rule_result["confidence"]

    logger.debug(f"规则引擎结果: type={rule_doc_type}, confidence={rule_confidence:.2f}")

    # 高置信度直接返回（关键词命中较多）
    if rule_confidence >= 0.7 and rule_doc_type != "general_document":
        logger.info(f"规则快速通道命中: type={rule_doc_type}")
        return {
            "document_type": rule_doc_type,
            "confidence": rule_confidence,
        }

    # 2. LLM tool calling 路径
    try:
        # 截取内容前 2000 字，避免 token 过长
        content_preview = content[:2000] if len(content) > 2000 else content

        llm_with_tools = get_llm_with_tools(DOC_TYPE_TOOLS)
        messages = [
            SystemMessage(content=get_document_type_prompt()),
            HumanMessage(content=f"请分类以下文档内容：\n\n{content_preview}"),
        ]

        response = await llm_with_tools.ainvoke(messages)

        # 解析 tool_calls
        if response.tool_calls:
            tool_name = response.tool_calls[0]["name"]
            doc_type = DOC_TOOL_NAME_TO_TYPE.get(tool_name, "general_document")
            logger.info(f"LLM tool calling 结果: type={doc_type}")
            return {
                "document_type": doc_type,
                "confidence": 0.9,
            }

        # 没有调用工具，尝试自由文本解析
        content_text = response.content.strip().lower()
        type_keywords = {
            "financial_report": ["financial_report", "财务"],
            "etf_report": ["etf_report", "etf", "基金"],
            "news_article": ["news_article", "新闻"],
            "regulatory_document": ["regulatory_document", "法规", "监管"],
        }

        for dtype, keywords in type_keywords.items():
            if any(kw in content_text for kw in keywords):
                logger.info(f"LLM 自由文本解析: type={dtype}")
                return {"document_type": dtype, "confidence": 0.7}

        logger.info("LLM 未分类，使用 general_document")
        return {"document_type": "general_document", "confidence": 0.5}

    except Exception as e:
        logger.warning(f"LLM 分类失败，降级到规则引擎: {e}")
        return {
            "document_type": rule_doc_type,
            "confidence": rule_confidence,
        }


async def analyze_structure_node(state: DocumentState) -> Dict[str, Any]:
    """
    文档结构分析节点

    复用 DocumentAgent 的结构分析逻辑，不需要 LLM。

    Args:
        state: 当前状态

    Returns:
        状态更新字典：{key_info_locations, content_structure, suggested_chunk_strategy}
    """
    content = state["content"]
    doc_type = state.get("document_type", "general_document")

    logger.debug(f"文档结构分析开始: type={doc_type}")

    rule_agent = _get_rule_agent()

    # 查找关键信息位置
    key_info_locations = rule_agent._find_key_info_locations(content, doc_type)

    # 分析内容结构
    content_structure = rule_agent._analyze_content_structure(content)

    # 获取推荐分块策略
    suggested_chunk_strategy = rule_agent._get_chunk_strategy(doc_type)

    logger.debug(
        f"结构分析完成: {len(key_info_locations)} 个关键位置, "
        f"{content_structure.get('total_paragraphs', 0)} 个段落"
    )

    return {
        "key_info_locations": key_info_locations,
        "content_structure": content_structure,
        "suggested_chunk_strategy": suggested_chunk_strategy,
    }
