from typing import Optional
from server.models.decision import DecisionResult
import logging

# 获取模块级别日志记录器
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
        
        # 扩展的比较类关键词，包含各种口语化和模糊表达
        comparison_keywords = [
            # 中文明确比较
            "比较", "对比", "差异", "区别", "差别", "不同点",
            # 中文口语化表达
            "有啥不同", "有啥区别", "有什么区别", "有何不同", "有何区别",
            "哪个好", "哪个更好", "哪个更", "哪个比较", "哪一款",
            "有什么不一样", "哪里不一样", "哪儿不同", "怎么不一样",
            "比一比", "比比看", "对比一下", "比较一下",
            "优劣", "优缺点", "优势劣势", "长处短处",
            "相对", "相比较", "相比", "比起来", "相较",
            "异同", "异同点", "相同点和不同点",
            "vs", "VS", "versus", "V.S.", "vs.",  # 英文缩写
            # 英文表达
            "compare", "comparison", "difference", "different", "diff",
            "versus", "vs", "contrast", "distinguish", "distinction",
            # 中文模糊表达
            "怎么选", "如何选择", "选哪个", "选择哪个", "应该选",
            "好还是", "还是好", "好一点", "更好些",
            "强的", "更强的", "优势在", "缺点在",
            "谁更", "什么更", "哪种更",
            # 中英文混合
            "compare一下", "对比compare", "different在哪里",
            # 句式结构关键词
            "和", "与", "跟", "同", "及", "以及",  # 连接词（配合其他词判断）
            "哪个", "哪种", "哪款", "哪一项",  # 疑问词
            "更好", "更优", "更合适", "更适合",  # 比较级
            "最", "最优", "最好", "最佳", "最强",  # 最高级
        ]
        
        # 检测比较类问题
        # 首先检查是否包含明确的比较关键词
        has_comparison_keyword = any(keyword in q for keyword in comparison_keywords)
        
        # 检查特定句式模式
        has_comparison_pattern = False
        comparison_patterns = [
            # A和B哪个好
            lambda s: any(conn in s for conn in ["和", "与", "跟", "同"]) and any(q_word in s for q_word in ["哪个", "哪种", "哪款"]),
            # 哪个更X
            lambda s: "哪个" in s and any(comp in s for comp in ["更", "比较", "相对"]),
            # A vs B
            lambda s: " vs " in s or " versus " in s,
            # 好还是不好
            lambda s: "还是" in s and ("好" in s or "更好" in s or "更" in s),
            # 有什么区别/不同
            lambda s: ("什么" in s or "有啥" in s or "有何" in s) and any(diff in s for diff in ["区别", "不同", "差别", "差异"]),
            # 优劣势/优缺点
            lambda s: any(term in s for term in ["优劣", "优缺点", "优点缺点", "优势劣势"]),
        ]
        
        for pattern in comparison_patterns:
            if pattern(q):
                has_comparison_pattern = True
                break
        
        if has_comparison_keyword or has_comparison_pattern:
            logger.debug("检测到比较类问题")
            intent = "comparison"
            top_k = 8  # 比较类问题需要更多上下文
            output_format = "table"  # 比较类问题以表格形式输出
        # 检测摘要类问题
        elif any(k in q for k in ["摘要", "总结", "总结一下", "概括", "概述", "简述", "简要说明"]):
            logger.debug("检测到摘要类问题")
            intent = "summary"
            top_k = 4  # 摘要类问题需要较少文本块
            output_format = "text"
        # 检测趋势类问题
        elif any(k in q for k in ["趋势", "趋势性", "未来", "发展", "走向", "方向", "前景", "预测"]):
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