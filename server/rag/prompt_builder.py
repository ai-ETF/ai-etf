from typing import List, Dict
import logging

logger = logging.getLogger(__name__)


def build_prompt(question: str, decision: Dict, chunks: List[Dict], format_analysis: Dict = None) -> str:
    """
    根据问题、决策和相关文本块构建完整的提示词

    参数:
        question: 用户的问题
        decision: 决策结果字典（包含意图、输出格式等）
        chunks: 检索到的相关文本块列表
        format_analysis: 输出格式分析结果（可选）

    返回:
        构建完成的提示词字符串
    """
    logger.debug(f"开始构建提示词")
    logger.debug(f"问题: {question}")
    logger.debug(f"决策: {decision}")
    logger.debug(f"相关文本块数量: {len(chunks)}")
    logger.debug(f"输出格式分析: {format_analysis}")

    lines = []
    # 添加决策信息部分
    logger.debug("添加决策信息部分")
    lines.append("# Decision:\n")
    lines.append(f"Intent: {decision.get('intent')}\n")
    lines.append(f"Output format: {decision.get('output_format')}\n")

    # 如果有格式分析结果，添加格式信息
    if format_analysis:
        logger.debug("添加格式分析信息")
        lines.append(f"Primary format: {format_analysis.get('primary_format', 'N/A')}\n")
        lines.append(f"Format description: {format_analysis.get('format_description', 'N/A')}\n")
        lines.append(f"Formatting instructions: {format_analysis.get('formatting_instructions', 'N/A')}\n")

    lines.append("\n# Context:\n")

    logger.debug("添加上下文文本块")
    # 添加上下文文本块
    for i, c in enumerate(chunks):
        # 兼容我们新构建的 field name
        score = c.get('rerank_score') if c.get('rerank_score', None) is not None else c.get('similarity')

        # 使用安全的格式化方式处理可能为None的分数
        score_str = f"{score:.4f}" if score is not None and isinstance(score, (int, float)) else "N/A"
        logger.debug(f"添加文本块 {i+1}，得分: {score_str}")
        lines.append(f"--- Chunk {i+1} (score={score_str}) ---\n")
        content = c.get('content', '') or c.get('text', '')
        lines.append(content + "\n\n")

    logger.debug("添加问题部分")
    # 添加问题部分
    lines.append("# Question:\n")
    lines.append(question + "\n")

    logger.debug("添加指令部分")
    lines.append("\n# Instructions:\n")

    # 防幻觉护栏：强制验真 + 拒绝编造
    lines.append(
        "你是一个严肃的 ETF 金融知识助手。请遵循以下绝对原则回答用户问题：\n\n"
        "1.【事实隔离】：请仔细阅读上方的 Context 文本块，评价它们是否包含回答 Question 所需的足够信息。\n"
        "2.【拒绝幻觉】：如果 Context 中没有给出明确答案、或者全部是无关内容，你**必须**输出："
        "「抱歉，当前的知识库中未找到相关事实，我无法回答该问题。」"
        "**绝对不允许**调用你的内部知识去猜测或补充。\n"
        "3.【格式对齐】：如果能找到答案，请根据下方的格式要求进行输出，语言要对金融新手友好。\n\n"
    )

    # 格式指令
    if format_analysis and format_analysis.get('formatting_instructions'):
        logger.debug("使用输出格式智能体的指令")
        lines.append(format_analysis['formatting_instructions'] + "\n")
    elif decision.get("intent") == "comparison":
        logger.debug("添加比较类问题指令")
        lines.append("请使用对比表格展示差异，包含关键指标的对比。\n")
    elif decision.get("intent") == "summary":
        logger.debug("添加摘要类问题指令")
        lines.append("请用要点列表总结关键信息。\n")
    else:
        logger.debug("添加通用问题指令")
        lines.append("请根据上方 Context 中的信息回答问题。\n")

    result = "\n".join(lines)
    logger.debug(f"提示词构建完成，总长度: {len(result)}")
    return result
