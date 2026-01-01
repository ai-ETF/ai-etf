from typing import List, Dict
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def build_prompt(question: str, decision: Dict, chunks: List[Dict]) -> str:
    """
    根据问题、决策和相关文本块构建完整的提示词
    
    参数:
        question: 用户的问题
        decision: 决策结果字典（包含意图、输出格式等）
        chunks: 检索到的相关文本块列表
        
    返回:
        构建完成的提示词字符串
    """
    logger.debug(f"开始构建提示词")
    logger.debug(f"问题: {question}")
    logger.debug(f"决策: {decision}")
    logger.debug(f"相关文本块数量: {len(chunks)}")
    
    lines = []
    # 添加决策信息部分
    logger.debug("添加决策信息部分")
    lines.append("# Decision:\n")
    lines.append(f"Intent: {decision.get('intent')}\n")
    lines.append(f"Output format: {decision.get('output_format')}\n")
    lines.append("\n# Context:\n")
    
    logger.debug("添加上下文文本块")
    # 添加上下文文本块
    for i, c in enumerate(chunks):
        logger.debug(f"添加文本块 {i+1}，得分: {c.get('score'):.4f}")
        lines.append(f"--- Chunk {i+1} (score={c.get('score'):.4f}) ---\n")
        lines.append(c.get("text") + "\n\n")
    
    logger.debug("添加问题部分")
    # 添加问题部分
    lines.append("# Question:\n")
    lines.append(question + "\n")
    
    logger.debug("添加指令部分")
    # 添加指令部分，根据意图不同使用不同指令
    lines.append("\n# Instructions:\n")
    if decision.get("intent") == "comparison":
        logger.debug("添加比较类问题指令")
        lines.append("Please produce a concise comparison table where relevant.\n")
    elif decision.get("intent") == "summary":
        logger.debug("添加摘要类问题指令")
        lines.append("Please summarize the key points using bullets.\n")
    else:
        logger.debug("添加通用问题指令")
        lines.append("Answer based on the provided context. If insufficient, say you don't know.\n")

    result = "\n".join(lines)
    logger.debug(f"提示词构建完成，总长度: {len(result)}")
    return result