from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class DocumentAgent:
    """
    文档智能体类
    负责分析文档类型、内容结构和关键信息区域
    """
    
    def __init__(self):
        """
        初始化文档智能体
        定义文档类型关键词映射
        """
        logger.debug("初始化文档智能体")
        
        # 定义不同文档类型的关键词映射
        self.document_type_keywords = {
            "financial_report": [
                "资产负债表", "利润表", "现金流量表", "财务报告", "财务摘要", 
                "净利润", "营业收入", "总资产", "股东权益", "财务状况"
            ],
            "etf_report": [
                "基金", "ETF", "净值", "持仓", "重仓", "基金合同", "招募说明书", 
                "基金概况", "投资策略", "风险提示", "基金评级", "基金管理人"
            ],
            "news_article": [
                "新闻", "报道", "消息", "记者", "采访", "事件", "分析", 
                "市场", "评论", "观点", "观察", "聚焦"
            ],
            "regulatory_document": [
                "法规", "监管", "政策", "通知", "规定", "办法", "指导意见", 
                "合规", "监管要求", "实施细则", "发布", "修订"
            ]
        }
        
        logger.debug(f"文档智能体初始化完成，已定义 {len(self.document_type_keywords)} 种文档类型")

    def analyze(self, content: str, doc_id: Optional[str] = None) -> Dict:
        """
        分析文档类型和结构
        
        参数:
            content: 文档内容
            doc_id: 文档ID（可选）
            
        返回:
            包含文档类型、关键信息位置等分析结果的字典
        """
        logger.debug(f"开始分析文档，文档ID: {doc_id}")
        logger.debug(f"文档内容长度: {len(content)} 字符")
        
        # 识别文档类型
        doc_type = self._identify_document_type(content)
        logger.debug(f"识别的文档类型: {doc_type}")
        
        # 识别关键信息区域
        key_info_locations = self._find_key_info_locations(content, doc_type)
        logger.debug(f"找到 {len(key_info_locations)} 个关键信息区域")
        
        # 分析内容结构
        content_structure = self._analyze_content_structure(content)
        logger.debug(f"内容结构分析完成")
        
        # 构建分析结果
        result = {
            "document_type": doc_type,
            "key_info_locations": key_info_locations,
            "content_structure": content_structure,
            "suggested_chunk_strategy": self._get_chunk_strategy(doc_type),
            "confidence": self._calculate_confidence(doc_type, content)
        }
        
        logger.debug(f"文档分析完成，结果: {result}")
        return result

    def _identify_document_type(self, content: str) -> str:
        """
        识别文档类型
        
        参数:
            content: 文档内容
            
        返回:
            识别出的文档类型
        """
        logger.debug("开始识别文档类型")
        
        # 统计各类型关键词出现次数
        type_scores = {}
        content_lower = content.lower()
        
        for doc_type, keywords in self.document_type_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword.lower() in content_lower:
                    score += 1
            type_scores[doc_type] = score
            logger.debug(f"  {doc_type}: 找到 {score} 个关键词")
        
        # 选择得分最高的类型
        if max(type_scores.values()) > 0:
            identified_type = max(type_scores, key=type_scores.get)
            logger.debug(f"文档类型识别结果: {identified_type} (得分: {type_scores[identified_type]})")
            return identified_type
        else:
            logger.debug("未识别到特定类型，返回默认类型: general_document")
            return "general_document"

    def _find_key_info_locations(self, content: str, doc_type: str) -> list:
        """
        查找关键信息位置
        
        参数:
            content: 文档内容
            doc_type: 文档类型
            
        返回:
            关键信息位置列表
        """
        logger.debug(f"查找 {doc_type} 类型文档的关键信息位置")
        
        key_locations = []
        lines = content.split('\n')
        
        # 根据文档类型查找特定关键词
        keywords = self.document_type_keywords.get(doc_type, [])
        
        for i, line in enumerate(lines):
            for keyword in keywords:
                if keyword in line:
                    key_locations.append({
                        "line_number": i,
                        "content_preview": line[:100],  # 只取前100个字符作为预览
                        "keyword": keyword
                    })
                    break  # 找到一个关键词后不再检查其他关键词
        
        # 去重并按行号排序
        unique_locations = []
        seen_lines = set()
        for loc in key_locations:
            if loc["line_number"] not in seen_lines:
                unique_locations.append(loc)
                seen_lines.add(loc["line_number"])
        
        unique_locations.sort(key=lambda x: x["line_number"])
        
        logger.debug(f"找到 {len(unique_locations)} 个唯一的关键信息位置")
        return unique_locations

    def _analyze_content_structure(self, content: str) -> Dict:
        """
        分析文档内容结构
        
        参数:
            content: 文档内容
            
        返回:
            内容结构分析结果
        """
        logger.debug("分析文档内容结构")
        
        lines = content.split('\n')
        paragraphs = [p for p in content.split('\n\n') if p.strip()]
        
        structure = {
            "total_lines": len(lines),
            "total_paragraphs": len(paragraphs),
            "avg_line_length": sum(len(line) for line in lines) / len(lines) if lines else 0,
            "avg_paragraph_length": sum(len(p) for p in paragraphs) / len(paragraphs) if paragraphs else 0,
            "has_tables": self._detect_tables(content),
            "has_lists": self._detect_lists(content)
        }
        
        logger.debug(f"内容结构分析结果: {structure}")
        return structure

    def _detect_tables(self, content: str) -> bool:
        """
        检测文档中是否包含表格
        
        参数:
            content: 文档内容
            
        返回:
            是否包含表格
        """
        # 简单检测表格特征（包含多个竖线或制表符）
        has_vertical_bars = '|' in content
        has_tabs = '\t' in content
        # 检查是否有类似 "项目 | 内容" 的结构
        import re
        table_pattern = r'\S+\s*\|\s*\S+'
        has_table_format = bool(re.search(table_pattern, content))
        
        has_table = has_vertical_bars or has_tabs or has_table_format
        logger.debug(f"表格检测结果: {has_table}")
        return has_table

    def _detect_lists(self, content: str) -> bool:
        """
        检测文档中是否包含列表
        
        参数:
            content: 文档内容
            
        返回:
            是否包含列表
        """
        # 检测常见的列表标记
        list_indicators = ['•', '·', '-', '1.', '2.', '3.', '一、', '二、', '首先', '其次', '最后']
        
        for indicator in list_indicators:
            if indicator in content:
                logger.debug(f"检测到列表标记: {indicator}")
                return True
        
        logger.debug("未检测到列表标记")
        return False

    def _get_chunk_strategy(self, doc_type: str) -> str:
        """
        根据文档类型获取推荐的分块策略
        
        参数:
            doc_type: 文档类型
            
        返回:
            推荐的分块策略
        """
        strategy_map = {
            "financial_report": "按财务报表章节分块，保持数据完整性",
            "etf_report": "按基金要素分块，如持仓、净值、评级等",
            "news_article": "按段落分块，保持新闻要素完整",
            "regulatory_document": "按条款分块，保持法规条文完整性",
            "general_document": "按自然段落分块"
        }
        
        strategy = strategy_map.get(doc_type, strategy_map["general_document"])
        logger.debug(f"推荐分块策略: {strategy}")
        return strategy

    def _calculate_confidence(self, doc_type: str, content: str) -> float:
        """
        计算文档类型识别的置信度
        
        参数:
            doc_type: 识别的文档类型
            content: 文档内容
            
        返回:
            置信度分数 (0-1)
        """
        if doc_type == "general_document":
            return 0.5  # 默认置信度
        
        # 计算关键词密度作为置信度指标
        keywords = self.document_type_keywords.get(doc_type, [])
        keyword_count = 0
        
        content_lower = content.lower()
        for keyword in keywords:
            keyword_count += content_lower.count(keyword.lower())
        
        # 基于关键词密度计算置信度
        if len(content) == 0:
            return 0.0
            
        keyword_density = keyword_count / len(content) * 1000  # 每千字符关键词数
        confidence = min(keyword_density * 2, 1.0)  # 最大置信度为1.0
        
        logger.debug(f"置信度计算 - 关键词数: {keyword_count}, 内容长度: {len(content)}, 置信度: {confidence:.2f}")
        return confidence