from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import re
import logging
from server.models.decision import DecisionResult

# 获取模块级别日志记录器
logger = logging.getLogger(__name__)

class IntentType(Enum):
    """
    ETF Agent意图类型枚举
    定义了Agent可以识别的各种问题类型
    """
    DOCUMENT_QUERY = "document_query"      # 文档查询
    ETF_COMPARISON = "etf_comparison"      # ETF对比
    RISK_ASSESSMENT = "risk_assement"      # 风险评估
    PORTFOLIO_ANALYSIS = "portfolio_analysis"  # 组合分析
    MARKET_DATA = "market_data"            # 市场数据
    HISTORY_CONTEXT = "history_context"    # 历史对话
    GENERAL_CHAT = "general_chat"          # 通用对话


@dataclass
class AgentDecision:
    """
    Agent决策结果数据类
    用于存储Agent的分析结果，包括意图、工具选择、置信度等信息
    """
    intent: IntentType           # 识别的意图类型
    selected_tool: str          # 选择的工具名称
    confidence: float           # 意图识别的置信度 (0.0-1.0)
    extracted_params: Dict[str, Any]  # 从问题中提取的参数
    needs_clarification: bool = False  # 是否需要进一步澄清
    clarification_message: Optional[str] = None  # 澄清提示信息


class ETFRuleBasedAgent:
    """
    ETF规则型Agent，不调用AI，只基于关键词和规则判断意图
    该Agent专注于ETF领域问题的意图识别和工具路由
    """

    def __init__(self):
        """
        初始化ETF规则型Agent
        设置关键词模式和优先级
        """
        self.keyword_patterns = self._initialize_patterns()
        logger.info("ETF规则型Agent初始化完成")

    def _initialize_patterns(self) -> Dict[IntentType, Dict[str, Any]]:
        """
        初始化关键词模式，返回结构：
        {
            IntentType.DOCUMENT_QUERY: {
                "keywords": ["什么是", "介绍", "文档"],
                "priority": 1,
                "required_params": []
            },
            ...
        }
        """
        patterns = {
            IntentType.DOCUMENT_QUERY: {
                "keywords": [
                    "什么是", "介绍", "文档", "说明", "详情", "定义", "含义", 
                    "解释", "了解一下", "介绍一下", "讲讲", "描述", "概念",
                    "有什么用", "怎么样", "是什么", "用途", "作用", "特点",
                    "基本信息", "概况", "简介", "资料", "信息", "查找",
                    "找一下", "搜索", "看看", "关于", "有关", "针对"
                ],
                "priority": 1,
                "required_params": []
            },
            IntentType.ETF_COMPARISON: {
                "keywords": [
                    "比较", "对比", "vs", "versus", "V.S.", "vs.", "相对",
                    "哪个好", "哪个更", "差别", "不同", "差异", "区别",
                    "哪个适合", "选哪个", "如何选择", "哪一个", "哪个更",
                    "哪个更有", "哪个更优", "哪个更强", "哪个更稳定",
                    "有啥不同", "有什么不同", "有什么区别", "哪个更合适",
                    "优劣", "优缺点", "优势劣势", "哪个表现更好",
                    "比一比", "比比看", "对比一下", "比较一下", "哪个强",
                    "哪个弱", "哪个收益高", "哪个风险小", "哪个更适合我"
                ],
                "priority": 2,
                "required_params": []  # 后续会通过专门的方法提取ETF代码
            },
            IntentType.RISK_ASSESSMENT: {
                "keywords": [
                    "风险", "安全", "风险性", "安全性", "波动", "波动性",
                    "稳定", "稳健", "稳妥", "可靠", "可靠性", "风险大吗",
                    "安全吗", "稳不稳定", "靠不靠谱", "有没有风险", "风险高不高",
                    "风险评估", "风险分析", "风险控制", "风控", "风险承受能力",
                    "抗风险", "风险等级", "风险系数", "风险程度", "风险暴露",
                    "风险分散", "风险规避", "风险防范", "风险管控", "风险抵御"
                ],
                "priority": 3,
                "required_params": []
            },
            IntentType.PORTFOLIO_ANALYSIS: {
                "keywords": [
                    "组合", "配置", "持仓", "分配", "比例", "布局", "分散",
                    "投资组合", "资产配置", "仓位", "权重", "配比", "构建",
                    "调整", "优化", "再平衡", "重新配置", "投资分布", "持有",
                    "我的投资", "我的组合", "如何配置", "怎样分配", "建议配置",
                    "合理分配", "科学配置", "组合建议", "配置策略", "投资建议",
                    "资产分布", "投资结构", "投资比例", "投资权重"
                ],
                "priority": 4,
                "required_params": []
            },
            IntentType.MARKET_DATA: {
                "keywords": [
                    "行情", "价格", "涨跌", "指标", "估值", "净值", "市盈率",
                    "市净率", "收益率", "分红", "成交", "走势", "K线", "趋势",
                    "数据", "实时", "今天", "昨天", "历史", "最新", "现在",
                    "目前", "近期", "近期表现", "近期走势", "今日", "昨日", "上周",
                    "上月", "去年", "今年", "今年以来", "最近", "最新数据",
                    "行情分析", "价格分析", "数据变化", "市场表现", "业绩表现"
                ],
                "priority": 5,
                "required_params": []
            },
            IntentType.HISTORY_CONTEXT: {
                "keywords": [
                    "刚才", "之前", "上次", "继续", "前面", "之前说的",
                    "之前提到的", "我们说到了", "我记得", "回过头", "回头看",
                    "接着说", "上次聊的", "刚才提到", "刚才讨论", "之前讨论",
                    "我们刚才", "我们之前", "我们上次", "上次说", "刚才说",
                    "之前说过", "刚才说了", "之前讲过", "刚才讲过", "前面提到"
                ],
                "priority": 6,
                "required_params": []
            },
            IntentType.GENERAL_CHAT: {
                "keywords": [
                    "你好", "谢谢", "好的", "可以", "没问题", "明白了",
                    "知道了", "懂了", "了解", "好的", "嗯", "哦", "啊",
                    "随便", "都可以", "试试", "测试", "hello", "hi",
                    "help", "帮助", "怎么办", "怎么搞", "咋办", "咋整"
                ],
                "priority": 7,
                "required_params": []
            }
        }
        return patterns

    def extract_parameters(self, question: str, intent: IntentType) -> Dict[str, Any]:
        """
        从问题中提取参数（如ETF代码、时间范围等）
        使用简单规则，不调用NLP
        
        Args:
            question: 用户问题
            intent: 意图类型
            
        Returns:
            提取的参数字典
        """
        params = {}
        
        # 更精确的ETF代码提取：匹配以51、15、56、58开头的6位数字
        etf_codes = re.findall(r'\b(51\d{4}|15\d{4}|56\d{4}|58\d{4})\b', question)
        if etf_codes:
            params['etf_codes'] = list(set(etf_codes))  # 去重
        
        # 提取中文ETF名称（改进版）
        # 先提取可能的ETF名称
        possible_names = []
        
        # 匹配 "XXETF" 格式
        names_with_etf = re.findall(r'([\u4e00-\u9fa5]{1,}[A-Z]*[0-9]*ETF)\b', question)
        possible_names.extend(names_with_etf)
        
        # 匹配常见的ETF名称（如"沪深300"、"创业板"等）
        common_etf_keywords = [
            "沪深300", "中证500", "创业板", "上证50", "科创50", "中证银行", 
            "中证白酒", "医药ETF", "消费ETF", "科技ETF", "芯片ETF", 
            "新能源车", "光伏产业", "5G通信", "证券ETF", "保险ETF", 
            "银行ETF", "黄金ETF", "石油ETF", "国债ETF", "纳指ETF", 
            "标普500", "日经225", "恒生ETF", "H股ETF", "国企ETF"
        ]
        for keyword in common_etf_keywords:
            if keyword in question:
                possible_names.append(keyword)
        
        # 过滤掉不是真实ETF名称的部分
        final_names = []
        for name in possible_names:
            clean_name = name.strip().replace('  ', ' ').replace('ETFETF', 'ETF')
            if clean_name != 'ETF' and len(clean_name) > 1:  # 排除单独的ETF
                final_names.append(clean_name)
        
        if final_names:
            params['etf_names'] = list(set(final_names))
        
        # 提取时间相关词汇
        time_patterns = [
            r'(最近|近期|近来|眼下|当前|目前).*?(\d+年|\d+个月|\d+天|\d+周)',
            r'(\d+年|\d+个月|\d+天|\d+周).*?(以来|以前|之前|到现在)',
            r'(过去|之前|上月|本月|上季度|本季度|去年|今年|去年至今|今年以来)',
        ]
        for pattern in time_patterns:
            matches = re.findall(pattern, question)
            if matches:
                params['time_range'] = [item for sublist in matches for item in sublist if item.strip()]
                
        # 如果是对比意图，尝试提取两个不同的ETF
        if intent == IntentType.ETF_COMPARISON:
            all_targets = []
            if 'etf_codes' in params:
                all_targets.extend(params['etf_codes'])
            if 'etf_names' in params:
                all_targets.extend(params['etf_names'])
            if len(all_targets) >= 2:
                params['comparison_targets'] = all_targets[:2]
        
        # 提取数值
        numbers = re.findall(r'(\d+(?:\.\d+)?)', question)
        if numbers:
            params['numbers'] = [float(n) for n in numbers]
        
        return params

    def calculate_confidence(self, question: str, intent: IntentType) -> float:
        """
        计算指定意图的置信度
        
        Args:
            question: 用户问题
            intent: 意图类型
            
        Returns:
            置信度分数 (0.0-1.0)
        """
        if intent not in self.keyword_patterns:
            return 0.0
            
        keywords = self.keyword_patterns[intent]["keywords"]
        matched_keywords = [kw for kw in keywords if kw in question.lower()]
        
        if not matched_keywords:
            return 0.0
            
        # 基础置信度取决于匹配的关键词数量和长度
        base_score = min(len(matched_keywords) * 0.2, 0.6)  # 最多0.6的基础分数
        
        # 加权得分：某些关键词更重要
        weight_score = 0
        
        # 特殊处理：对于ETF比较意图，如果有多个ETF相关实体或比较关键词，增加权重
        if intent == IntentType.ETF_COMPARISON:
            # 检查问题中是否有多个ETF相关术语
            etf_codes_count = len(re.findall(r'\b(51\d{4}|15\d{4}|56\d{4}|58\d{4})\b', question))
            common_etf_keywords = [
                "沪深300", "中证500", "创业板", "上证50", "科创50", "中证银行", 
                "中证白酒", "医药ETF", "消费ETF", "科技ETF", "芯片ETF", 
                "新能源车", "光伏产业", "5G通信", "证券ETF", "保险ETF", 
                "银行ETF", "黄金ETF", "石油ETF", "国债ETF", "纳指ETF", 
                "标普500", "日经225", "恒生ETF", "H股ETF", "国企ETF"
            ]
            etf_names_count = sum(1 for keyword in common_etf_keywords if keyword in question)
            
            if etf_codes_count >= 2 or etf_names_count >= 2:
                weight_score += 0.2  # 额外加分给包含多个ETF的情况
            
            # 检查是否包含特殊的比较词（如"哪个收益更高"）
            if "哪个" in question and ("收益" in question or "表现" in question or "增长" in question or "收益高"):
                weight_score += 0.4  # 额外加分给比较收益的问题
                
        # 其他意图的加权
        high_priority_keywords = ['比较', '对比', 'vs', '风险', '安全', '组合', '配置']
        for kw in matched_keywords:
            if kw in high_priority_keywords:
                weight_score += 0.1
                
        # 长度奖励：问题越长，匹配的可信度越高
        length_bonus = min(len(question) / 100 * 0.1, 0.15)  # 最多0.15的长度奖励
        
        total_score = min(base_score + weight_score + length_bonus, 1.0)
        return round(total_score, 2)

    def decide_intent(self, question: str, user_id: str, chat_id: str) -> AgentDecision:
        """
        核心决策逻辑：
        1. 关键词匹配
        2. 历史对话检查（如果需要）
        3. 参数提取
        4. 置信度计算
        
        Args:
            question: 用户问题
            user_id: 用户ID
            chat_id: 会话ID
            
        Returns:
            AgentDecision对象，包含意图、工具选择等信息
        """
        logger.debug(f"开始分析问题意图: {question}")
        
        # 计算每种意图的置信度
        intent_scores = {}
        for intent in IntentType:
            score = self.calculate_confidence(question, intent)
            if score > 0:
                intent_scores[intent] = score
        
        # 特殊处理：如果问题中包含"哪个"和"收益"或"表现"等词，强制识别为比较意图
        if "哪个" in question and ("收益" in question or "表现" in question or "增长" in question or "收益高"):
            # 检查是否至少有两个ETF相关实体
            etf_codes_count = len(re.findall(r'\b(51\d{4}|15\d{4}|56\d{4}|58\d{4})\b', question))
            common_etf_keywords = [
                "沪深300", "中证500", "创业板", "上证50", "科创50", "中证银行", 
                "中证白酒", "医药ETF", "消费ETF", "科技ETF", "芯片ETF", 
                "新能源车", "光伏产业", "5G通信", "证券ETF", "保险ETF", 
                "银行ETF", "黄金ETF", "石油ETF", "国债ETF", "纳指ETF", 
                "标普500", "日经225", "恒生ETF", "H股ETF", "国企ETF"
            ]
            etf_names_count = sum(1 for keyword in common_etf_keywords if keyword in question)
            
            if etf_codes_count >= 1 or etf_names_count >= 2:
                # 强制将意图设置为ETF比较
                best_intent = IntentType.ETF_COMPARISON
                confidence = max(intent_scores.get(IntentType.ETF_COMPARISON, 0.5), 0.7)  # 确保置信度不低于0.7
            else:
                # 如果没有足够的ETF实体，选择最高置信度的意图
                best_intent = max(intent_scores, key=intent_scores.get) if intent_scores else IntentType.DOCUMENT_QUERY
                confidence = intent_scores.get(best_intent, 0.3)
        else:
            # 正常处理
            if intent_scores:
                best_intent = max(intent_scores, key=intent_scores.get)
                confidence = intent_scores[best_intent]
            else:
                # 如果没有匹配到任何关键词，使用默认意图（文档查询）
                best_intent = IntentType.DOCUMENT_QUERY
                confidence = 0.3  # 较低的默认置信度
            
        # 提取参数
        extracted_params = self.extract_parameters(question, best_intent)
        
        # 检查是否需要澄清
        needs_clarification = False
        clarification_message = None
        
        # 对于比较意图，如果没有找到足够的ETF代码或名称，则需要澄清
        if best_intent == IntentType.ETF_COMPARISON:
            codes_count = len(extracted_params.get('etf_codes', []))
            names_count = len(extracted_params.get('etf_names', []))
            targets_count = len(extracted_params.get('comparison_targets', []))
            
            if targets_count < 2:
                needs_clarification = True
                clarification_message = "请提供您想要比较的两个ETF代码或名称，例如：510300和510050，或者沪深300ETF和创业板ETF"
        
        # 对于风险评估意图，如果问题过于宽泛，可能需要澄清
        if best_intent == IntentType.RISK_ASSESSMENT:
            codes_count = len(extracted_params.get('etf_codes', []))
            names_count = len(extracted_params.get('etf_names', []))
            
            if codes_count == 0 and names_count == 0:
                needs_clarification = True
                clarification_message = "请指明您想了解哪个ETF的风险情况，比如：510300ETF的风险如何？"
        
        # 创建决策结果
        decision = AgentDecision(
            intent=best_intent,
            selected_tool=self.get_tool_name(best_intent),
            confidence=confidence,
            extracted_params=extracted_params,
            needs_clarification=needs_clarification,
            clarification_message=clarification_message
        )
        
        logger.debug(f"意图分析完成: {decision}")
        return decision

    def get_tool_name(self, intent: IntentType) -> str:
        """
        将意图映射到工具名称
        
        Args:
            intent: 意图类型
            
        Returns:
            对应的工具名称
        """
        tool_mapping = {
            IntentType.DOCUMENT_QUERY: "document_search",
            IntentType.ETF_COMPARISON: "compare_etfs",
            IntentType.RISK_ASSESSMENT: "risk_assessment",
            IntentType.PORTFOLIO_ANALYSIS: "portfolio_analysis",
            IntentType.MARKET_DATA: "market_data",
            IntentType.HISTORY_CONTEXT: "history_context",
            IntentType.GENERAL_CHAT: "general_chat"
        }
        return tool_mapping.get(intent, "document_search")  # 默认工具


def test_etf_agent():
    """
    测试ETF规则型Agent的功能
    """
    agent = ETFRuleBasedAgent()
    
    # 测试案例
    test_cases = [
        {
            "question": "什么是沪深300ETF？",
            "expected_intent": IntentType.DOCUMENT_QUERY,
            "description": "测试1：明确的文档查询"
        },
        {
            "question": "比较一下510300和159915这两个ETF",
            "expected_intent": IntentType.ETF_COMPARISON,
            "description": "测试2：ETF对比"
        },
        {
            "question": "比较一下沪深300ETF和创业板ETF",
            "expected_intent": IntentType.ETF_COMPARISON,
            "description": "测试2b：ETF对比（中文名称）"
        },
        {
            "question": "这个510300ETF的风险大吗？",
            "expected_intent": IntentType.RISK_ASSESSMENT,
            "description": "测试3：风险相关"
        },
        {
            "question": "我的投资组合应该怎么调整？",
            "expected_intent": IntentType.PORTFOLIO_ANALYSIS,
            "description": "测试4：组合分析"
        },
        {
            "question": "告诉我一些信息",
            "expected_intent": IntentType.DOCUMENT_QUERY,
            "description": "测试5：意图模糊"
        },
        {
            "question": "帮我比较一下",
            "expected_intent": IntentType.ETF_COMPARISON,
            "description": "测试6：需要澄清",
            "expect_clarification": True
        },
        {
            "question": "510300ETF的风险如何",
            "expected_intent": IntentType.RISK_ASSESSMENT,
            "description": "测试7：风险评估带代码"
        },
        {
            "question": "中证500和创业板ETF哪个收益更高？",
            "expected_intent": IntentType.ETF_COMPARISON,
            "description": "测试8：中文名称对比"
        }
    ]
    
    print("开始测试ETF规则型Agent...")
    print("="*60)
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n{i}. {case['description']}")
        print(f"   问题: {case['question']}")
        
        # 假设的用户和会话ID
        decision = agent.decide_intent(case['question'], "test_user", "test_chat")
        
        print(f"   识别意图: {decision.intent.value}")
        print(f"   选择工具: {decision.selected_tool}")
        print(f"   置信度: {decision.confidence}")
        print(f"   提取参数: {decision.extracted_params}")
        print(f"   需要澄清: {decision.needs_clarification}")
        if decision.clarification_message:
            print(f"   澄清提示: {decision.clarification_message}")
            
        # 检查测试结果
        if case.get('expect_clarification'):
            success = decision.needs_clarification
            status = "✓" if success else "✗"
            print(f"   测试结果: {status} (需要澄清: {'✓' if success else '✗'})")
        else:
            success = decision.intent == case['expected_intent']
            status = "✓" if success else "✗"
            print(f"   测试结果: {status} (意图正确: {'✓' if success else '✗'})")


if __name__ == "__main__":
    test_etf_agent()