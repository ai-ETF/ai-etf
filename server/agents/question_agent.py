from typing import Optional
from server.models.decision import DecisionResult
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class QuestionAgent:
    """基于规则的智能体，用于分析问题意图和输出格式偏好"""

    def analyze(self, question: str, metadata: Optional[dict] = None) -> DecisionResult:
        """
        分析问题意图和输出格式
        
        参数:
            question: 用户提出的问题
            metadata: 可选的元数据（当前未使用）
            
        返回:
            DecisionResult: 包含意图、输出格式、top_k数量等信息的对象
        """
        logger.debug(f"开始分析问题: {question}")
        q = question.lower()
        intent = "general"  # 默认意图
        output_format = "text"  # 默认输出格式
        top_k = 5  # 默认返回文本块数量

        logger.debug("开始检测问题意图...")
        
        # 检测比较类问题
        if any(k in q for k in ["比较", "对比", "差异"]):
            logger.debug("检测到比较类问题")
            intent = "comparison"
            top_k = 8  # 比较类问题需要更多上下文
            output_format = "table"  # 比较类问题以表格形式输出
        # 检测摘要类问题
        elif any(k in q for k in ["摘要", "总结", "总结一下"]):
            logger.debug("检测到摘要类问题")
            intent = "summary"
            top_k = 4  # 摘要类问题需要较少文本块
            output_format = "text"
        # 检测趋势类问题
        elif any(k in q for k in ["趋势", "趋势性", "未来"]):
            logger.debug("检测到趋势类问题")
            intent = "trend"
            top_k = 6  # 趋势类问题需要适中数量的文本块
            output_format = "text"
        else:
            logger.debug("问题类型为通用型")
            
        logger.debug(f"意图分析完成，结果: intent={intent}, output_format={output_format}, top_k={top_k}")

        decision_result = DecisionResult(intent=intent, output_format=output_format, top_k=top_k, doc_filter=None)
        logger.debug(f"决策结果创建完成: {decision_result}")
        return decision_result