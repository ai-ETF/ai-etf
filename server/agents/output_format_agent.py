from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class OutputFormatAgent:
    """
    输出格式智能体类
    负责分析和决定AI回答的输出格式
    """
    
    def __init__(self):
        """
        初始化输出格式智能体
        定义不同问题类型对应的输出格式规则
        """
        logger.debug("初始化输出格式智能体")
        
        # 定义问题类型到输出格式的映射
        self.intent_to_format = {
            "comparison": {
                "primary_format": "table", 
                "secondary_formats": ["text", "list"],
                "instructions": "请使用对比表格展示差异，包含关键指标的对比"
            },
            "summary": {
                "primary_format": "bullet_points",
                "secondary_formats": ["text", "numbered_list"],
                "instructions": "请使用要点总结关键信息，分点列出主要观点"
            },
            "trend": {
                "primary_format": "text",
                "secondary_formats": ["list", "timeline"],
                "instructions": "请按时间顺序或逻辑顺序描述趋势变化"
            },
            "general": {
                "primary_format": "text",
                "secondary_formats": ["list", "bullet_points"],
                "instructions": "请以自然语言回答问题，保持逻辑清晰"
            }
        }
        
        # 定义输出格式的详细规范
        self.format_specifications = {
            "table": {
                "description": "表格格式，适合对比类信息",
                "structure": ["表头", "行数据", "对比项"],
                "elements": ["列标题", "单元格内容", "分隔线"]
            },
            "bullet_points": {
                "description": "要点列表，适合总结类信息",
                "structure": ["项目符号", "要点内容", "层级关系"],
                "elements": ["•", "摘要文字", "缩进"]
            },
            "numbered_list": {
                "description": "编号列表，适合步骤或顺序类信息",
                "structure": ["序号", "列表项", "顺序关系"],
                "elements": ["数字编号", "列表内容", "序列"]
            },
            "text": {
                "description": "自然文本，适合解释说明类信息",
                "structure": ["段落", "句子", "逻辑连接"],
                "elements": ["文字", "标点", "段落分隔"]
            },
            "timeline": {
                "description": "时间线格式，适合趋势或历史类信息",
                "structure": ["时间点", "事件", "时间顺序"],
                "elements": ["时间戳", "事件描述", "连接线"]
            }
        }
        
        logger.debug(f"输出格式智能体初始化完成，已定义 {len(self.intent_to_format)} 种问题类型格式映射")

    def analyze(self, intent: str, content: str = "", user_preference: Optional[Dict] = None) -> Dict[str, Any]:
        """
        分析并确定最适合的输出格式
        
        参数:
            intent: 问题意图类型
            content: 上下文内容（可选，用于更精确的格式选择）
            user_preference: 用户格式偏好（可选）
            
        返回:
            包含输出格式、指令和规范的分析结果字典
        """
        logger.debug(f"开始分析输出格式，问题意图: {intent}")
        logger.debug(f"用户偏好: {user_preference}")
        
        # 获取基于意图的格式建议
        format_suggestion = self._get_format_by_intent(intent)
        logger.debug(f"基于意图的格式建议: {format_suggestion}")
        
        # 根据内容和用户偏好调整格式
        final_format = self._adjust_format_by_context(
            format_suggestion, 
            content, 
            user_preference
        )
        logger.debug(f"最终格式选择: {final_format}")
        
        # 生成格式化指令
        formatting_instructions = self._generate_formatting_instructions(final_format, intent)
        logger.debug(f"格式化指令: {formatting_instructions}")
        
        # 构建分析结果
        result = {
            "primary_format": final_format["primary_format"],
            "secondary_formats": final_format["secondary_formats"],
            "format_description": self.format_specifications.get(final_format["primary_format"], {}).get("description", ""),
            "format_elements": self.format_specifications.get(final_format["primary_format"], {}).get("elements", []),
            "formatting_instructions": formatting_instructions,
            "confidence": self._calculate_format_confidence(intent, user_preference)
        }
        
        logger.debug(f"输出格式分析完成，结果: {result}")
        return result

    def _get_format_by_intent(self, intent: str) -> Dict[str, Any]:
        """
        根据问题意图获取推荐的输出格式
        
        参数:
            intent: 问题意图类型
            
        返回:
            推荐的格式信息
        """
        logger.debug(f"根据意图 '{intent}' 获取格式建议")
        
        # 如果意图不在预定义列表中，使用默认格式
        if intent not in self.intent_to_format:
            logger.warning(f"未知意图类型 '{intent}'，使用默认格式")
            intent = "general"
        
        suggestion = self.intent_to_format[intent].copy()
        suggestion["intent"] = intent
        
        logger.debug(f"意图 {intent} 的格式建议: {suggestion}")
        return suggestion

    def _adjust_format_by_context(
        self, 
        base_format: Dict[str, Any], 
        content: str, 
        user_preference: Optional[Dict]
    ) -> Dict[str, Any]:
        """
        根据上下文内容和用户偏好调整输出格式
        
        参数:
            base_format: 基础格式建议
            content: 上下文内容
            user_preference: 用户格式偏好
            
        返回:
            调整后的格式信息
        """
        logger.debug(f"根据上下文调整格式，用户偏好: {user_preference}")
        
        # 复制基础格式
        adjusted_format = base_format.copy()
        
        # 如果用户有明确偏好，优先使用用户偏好
        if user_preference and "preferred_format" in user_preference:
            preferred_format = user_preference["preferred_format"]
            logger.debug(f"检测到用户偏好格式: {preferred_format}")
            
            # 验证格式是否支持
            if preferred_format in self.format_specifications:
                logger.debug(f"用户偏好格式有效，更新主格式为: {preferred_format}")
                adjusted_format["primary_format"] = preferred_format
            else:
                logger.warning(f"用户偏好格式 '{preferred_format}' 不支持，保持原格式")
        
        # 根据内容特征调整格式（简单实现，可根据需要扩展）
        if content:
            # 如果内容较短，可能更适合要点列表
            if len(content) < 200 and "bullet_points" in adjusted_format["secondary_formats"]:
                logger.debug("内容较短，考虑使用要点列表格式")
        
        logger.debug(f"调整后的格式: {adjusted_format}")
        return adjusted_format

    def _generate_formatting_instructions(self, final_format: Dict[str, Any], intent: str) -> str:
        """
        生成格式化指令
        
        参数:
            final_format: 最终格式选择
            intent: 问题意图类型
            
        返回:
            格式化指令字符串
        """
        logger.debug(f"为格式 {final_format['primary_format']} 生成格式化指令")
        
        base_instruction = final_format.get("instructions", "")
        
        # 根据格式类型添加特定指令
        format_type = final_format["primary_format"]
        if format_type == "table":
            instruction = base_instruction + "。表格应包含清晰的表头和对比项，使用markdown格式。"
        elif format_type == "bullet_points":
            instruction = base_instruction + "。使用markdown列表格式，每点不超过两行。"
        elif format_type == "numbered_list":
            instruction = base_instruction + "。使用编号列表，确保步骤或顺序清晰。"
        elif format_type == "timeline":
            instruction = base_instruction + "。按时间顺序组织信息，突出关键时间节点。"
        else:
            instruction = base_instruction + "。保持回答结构清晰，逻辑连贯。"
        
        logger.debug(f"生成的格式化指令: {instruction}")
        return instruction

    def _calculate_format_confidence(self, intent: str, user_preference: Optional[Dict]) -> float:
        """
        计算格式选择的置信度
        
        参数:
            intent: 问题意图类型
            user_preference: 用户格式偏好
            
        返回:
            置信度分数 (0-1)
        """
        logger.debug(f"计算格式选择置信度，意图: {intent}")
        
        # 基础置信度取决于意图类型
        base_confidence = 0.7  # 默认置信度
        
        # 如果用户有明确偏好，提高置信度
        if user_preference and "preferred_format" in user_preference:
            logger.debug("检测到用户偏好，提高置信度")
            user_pref_confidence = 0.9
        else:
            user_pref_confidence = 0.0
        
        # 综合计算置信度
        final_confidence = (base_confidence + user_pref_confidence) / 2
        
        logger.debug(f"格式选择置信度: {final_confidence}")
        return final_confidence