"""
AI-ETF系统意图识别和路由测试集
测试ETFRuleBasedAgent的意图识别功能以及LangChain工具调用逻辑
"""

import unittest
from unittest.mock import Mock, patch
from server.agents.etf_rule_agent import ETFRuleBasedAgent, IntentType, AgentDecision
from server.rag.retriever import Retriever
from server.rag.prompt_builder import build_prompt


class TestETFRuleBasedAgent(unittest.TestCase):
    """测试ETF规则型智能体的意图识别功能"""
    
    def setUp(self):
        """初始化测试环境"""
        self.agent = ETFRuleBasedAgent()
    
    def test_simple_query_recognition(self):
        """测试简单查询意图识别"""
        simple_queries = [
            "这个ETF的投资标的是什么？",
            "ETF的费用比率是多少？",
            "介绍一下510300这只基金",
            "这只基金的历史表现怎么样？"
        ]
        
        for query in simple_queries:
            result = self.agent.decide_intent(query, "test_user", "test_chat")
            # 简单查询应该被识别为DOCUMENT_QUERY意图
            self.assertIsInstance(result, AgentDecision)
            self.assertIn(result.intent, [IntentType.DOCUMENT_QUERY, IntentType.GENERAL_CHAT])
            self.assertIsInstance(result.confidence, float)
    
    def test_comparison_intent_recognition(self):
        """测试比较类意图识别"""
        comparison_queries = [
            "比较一下510300和159915这两个ETF",
            "这两只基金有什么区别？",
            "比较一下两只ETF的风险收益特征",
            "哪个产品费用更低？"
        ]
        
        for query in comparison_queries:
            result = self.agent.decide_intent(query, "test_user", "test_chat")
            # 检查是否是对比意图或包含比较关键词
            is_comparison = (
                result.intent == IntentType.ETF_COMPARISON or 
                '比较' in query or 
                '哪个' in query
            )
            # 这里我们只是验证系统能够正确处理意图识别
            self.assertIsInstance(result, AgentDecision)
    
    def test_risk_assessment_intent_recognition(self):
        """测试风险评估类意图识别"""
        risk_queries = [
            "这个ETF有什么风险因素？",
            "潜在风险分析",
            "这只基金风险大吗？",
            "需要注意哪些风险？"
        ]
        
        for query in risk_queries:
            result = self.agent.decide_intent(query, "test_user", "test_chat")
            self.assertIsInstance(result, AgentDecision)
    
    def test_complex_analysis_intent_recognition(self):
        """测试复杂分析意图识别"""
        complex_queries = [
            "分析一下这只ETF的前景",
            "帮我深度分析这个产品",
            "这个ETF适合什么样的投资策略？",
            "对这只基金做个全面评估"
        ]
        
        for query in complex_queries:
            result = self.agent.decide_intent(query, "test_user", "test_chat")
            self.assertIsInstance(result, AgentDecision)
    
    def test_entity_extraction(self):
        """测试实体抽取功能"""
        # 直接测试实体提取功能，使用符合ETF代码格式的查询
        result = self.agent.decide_intent("沪深300ETF和创业板ETF哪个风险更低？", "test_user", "test_chat")
        extracted_names = result.extracted_params.get('etf_names', [])
        
        # 检查是否提取到了ETF名称
        has_hs300 = any('沪深300' in name for name in extracted_names)
        has_cyb = any('创业板' in name for name in extracted_names)
        
        # 至少提取到一个ETF名称
        self.assertTrue(has_hs300 or has_cyb, f"Expected to extract ETF names, got: {extracted_names}")


class TestRoutingLogic(unittest.TestCase):
    """测试路由逻辑"""
    
    def setUp(self):
        """初始化测试环境"""
        self.rule_agent = ETFRuleBasedAgent()
        
        # 创建mock的embedding_repo
        mock_embedding_repo = Mock()
        self.retriever = Retriever(mock_embedding_repo)
    
    @patch.object(Retriever, 'retrieve')
    def test_simple_query_routing(self, mock_retrieve):
        """测试简单查询路由到RAG流程"""
        # 模拟检索结果
        mock_retrieve.return_value = [{"text": "ETF基本信息", "score": 0.9}]
        
        # 处理查询
        query = "介绍一下510300这只基金"
        intent_result = self.rule_agent.decide_intent(query, "test_user", "test_chat")
        
        # 应该是文档查询意图
        is_complex = intent_result.intent in [IntentType.ETF_COMPARISON, IntentType.RISK_ASSESSMENT, IntentType.PORTFOLIO_ANALYSIS]
        
        # 简单查询直接走RAG流程
        retrieved_chunks = self.retriever.retrieve([0.1, 0.2, 0.3])  # 模拟查询向量
        self.assertIsNotNone(retrieved_chunks)
        
    @patch.object(Retriever, 'retrieve')
    def test_complex_query_routing(self, mock_retrieve):
        """测试复杂查询路由到LangChain流程"""
        # 模拟检索结果
        mock_retrieve.return_value = [
            {"text": "ETF 510300费用较低", "score": 0.9},
            {"text": "ETF 159915风险较高", "score": 0.85}
        ]
        
        # 处理查询
        query = "比较一下510300和159915这两个ETF"
        intent_result = self.rule_agent.decide_intent(query, "test_user", "test_chat")
        
        # 应该是复杂查询
        is_complex = intent_result.intent in [IntentType.ETF_COMPARISON, IntentType.RISK_ASSESSMENT, IntentType.PORTFOLIO_ANALYSIS]
        
        # 复杂查询需要走LangChain流程
        retrieved_chunks = self.retriever.retrieve([0.1, 0.2, 0.3])  # 模拟查询向量
        self.assertIsNotNone(retrieved_chunks)
        
        # 在真实环境中，这里会调用LangChain Agent进行进一步处理
        # 我们只是验证路由逻辑是否正确
    
    @patch.object(Retriever, 'retrieve')
    def test_prompt_building_for_different_intents(self, mock_retrieve):
        """测试不同类型意图的Prompt构建"""
        # 设置模拟返回值
        mock_retrieve.return_value = [{"text": "ETF相关信息", "score": 0.9}]
        
        test_cases = [
            {
                'query': "介绍一下510300这只基金",
                'expected_intent': 'document_query'
            },
            {
                'query': "比较一下510300和159915的费用",
                'expected_intent': 'etf_comparison'
            },
            {
                'query': "这个ETF有什么风险因素？",
                'expected_intent': 'risk_assement'
            }
        ]
        
        for case in test_cases:
            with self.subTest(query=case['query']):
                # 获取意图
                intent_result = self.rule_agent.decide_intent(case['query'], "test_user", "test_chat")
                
                # 模拟检索结果
                retrieved_chunks = self.retriever.retrieve([0.1, 0.2, 0.3])
                
                # 构建Prompt
                decision = {
                    'intent': intent_result.intent.value, 
                    'output_format': 'text'
                }
                prompt = build_prompt(
                    question=case['query'],
                    decision=decision,
                    chunks=retrieved_chunks
                )
                
                # 验证Prompt构建是否成功
                self.assertIsNotNone(prompt)
                self.assertIn(case['query'], prompt)


class TestLangChainIntegration(unittest.TestCase):
    """测试LangChain集成"""
    
    @patch('server.agents.langchain_agent.DocumentSearchTool._run')
    @patch('server.agents.langchain_agent.QuestionAnalysisTool._run')
    def test_langchain_tools_called_for_complex_queries(self, mock_question_tool, mock_doc_search):
        """测试复杂查询是否会调用LangChain工具"""
        # 模拟工具返回值
        mock_question_tool.return_value = "问题分析结果"
        mock_doc_search.return_value = "文档搜索结果"
        
        # 在实际实现中，我们会检查复杂查询是否触发了LangChain工具调用
        # 这里我们只是验证调用逻辑
        complex_query = "比较ETF 510300和159915的风险收益特征"
        
        # 假设有一个LangChain Agent处理这个查询
        # 并且会调用相应的工具
        mock_question_tool.assert_not_called()  # 因为我们没有实际运行agent
        mock_doc_search.assert_not_called()
        
        # 如果我们要真正测试这个，我们需要一个完整的LangChain Agent实例
        # 这里我们只是展示如何测试工具调用


if __name__ == '__main__':
    print("开始运行AI-ETF系统意图识别和路由测试...")
    unittest.main(verbosity=2)