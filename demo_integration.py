#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LangChain Agent与原智能体集成演示脚本
展示了如何使用LangChain工具调用原智能体功能
"""
import os
import sys
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 添加项目根目录到sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def demo_original_agents():
    """演示原智能体功能"""
    logger.info("="*60)
    logger.info("演示原智能体功能:")
    
    # 演示QuestionAgent
    from server.agents.question_agent import QuestionAgent
    question_agent = QuestionAgent()
    question = "我想比较一下510300和159915这两个ETF基金，哪个风险更低？"
    decision = question_agent.analyze(question)
    logger.info(f"问题: {question}")
    logger.info(f"意图: {decision.intent}")
    logger.info(f"输出格式: {decision.output_format}")
    logger.info(f"返回块数: {decision.top_k}")
    logger.info("-" * 40)

    # 演示OutputFormatAgent
    from server.agents.output_format_agent import OutputFormatAgent
    output_agent = OutputFormatAgent()
    format_analysis = output_agent.analyze(decision.intent, question)
    logger.info(f"输出格式分析:")
    logger.info(f"主格式: {format_analysis['primary_format']}")
    logger.info(f"格式描述: {format_analysis['format_description']}")
    logger.info(f"格式元素: {format_analysis['format_elements']}")
    logger.info("-" * 40)

    # 演示DocumentAgent
    from server.agents.document_agent import DocumentAgent
    doc_agent = DocumentAgent()
    sample_content = "这是一份关于华夏沪深300ETF基金的报告，该基金追踪沪深300指数，费率较低，适合长期投资。"
    doc_analysis = doc_agent.analyze(sample_content)
    logger.info(f"文档内容: {sample_content}")
    logger.info(f"文档类型: {doc_analysis['document_type']}")
    logger.info(f"关键信息位置: {len(doc_analysis['key_info_locations'])} 个")
    logger.info(f"置信度: {doc_analysis['confidence']}")
    logger.info("="*60)


def demo_langchain_tools():
    """演示LangChain工具封装"""
    logger.info("演示LangChain工具封装:")
    
    # 演示QuestionAnalysisTool
    from server.agents.langchain_agent import QuestionAnalysisTool
    question_tool = QuestionAnalysisTool()
    question = "510300和159919哪个更适合稳健型投资者？"
    result = question_tool._run(question=question)
    logger.info(f"问题: {question}")
    logger.info(f"LangChain工具结果: {result}")
    logger.info("-" * 40)

    # 演示OutputFormatAnalysisTool
    from server.agents.langchain_agent import OutputFormatAnalysisTool
    format_tool = OutputFormatAnalysisTool()
    result = format_tool._run(intent="comparison", question=question)
    logger.info(f"LangChain格式分析工具结果: {result}")
    logger.info("-" * 40)

    # 演示DocumentAnalysisTool
    from server.agents.langchain_agent import DocumentAnalysisTool
    doc_tool = DocumentAnalysisTool()
    sample_content = "易方达中证500ETF基金跟踪中证500指数，管理费率为0.5%，适合看好中小盘股票的投资者。"
    result = doc_tool._run(content=sample_content)
    logger.info(f"文档内容: {sample_content}")
    logger.info(f"LangChain文档分析工具结果: {result}")
    logger.info("="*60)


def demo_rule_based_agent():
    """演示规则型Agent"""
    logger.info("演示规则型Agent:")
    
    from server.agents.etf_rule_agent import ETFRuleBasedAgent
    rule_agent = ETFRuleBasedAgent()
    
    # 测试不同类型的意图
    questions = [
        "什么是ETF基金？",
        "比较一下510300和510050的费用",
        "510300的风险如何？",
        "帮我分析一下我的投资组合"
    ]
    
    for question in questions:
        decision = rule_agent.decide_intent(question, "user123", "chat456")
        logger.info(f"问题: {question}")
        logger.info(f"意图: {decision.intent.name}")
        logger.info(f"置信度: {decision.confidence:.2f}")
        logger.info(f"推荐工具: {decision.selected_tool}")
        logger.info("-" * 40)
    
    logger.info("="*60)


def demo_integration_flow():
    """演示完整的集成流程"""
    logger.info("演示完整集成流程:")
    
    # 假设用户问了一个比较问题
    user_question = "请帮我比较一下510300和510500这两个ETF基金"
    logger.info(f"用户问题: {user_question}")
    
    # 1. 规则型Agent识别意图
    from server.agents.etf_rule_agent import ETFRuleBasedAgent
    rule_agent = ETFRuleBasedAgent()
    agent_decision = rule_agent.decide_intent(user_question, "user123", "chat456")
    logger.info(f"1. 意图识别: {agent_decision.intent.name} -> 工具: {agent_decision.selected_tool}")
    
    # 2. 根据意图选择LangChain工具
    from server.agents.langchain_agent import map_rule_agent_decision_to_tool
    selected_tool = map_rule_agent_decision_to_tool(agent_decision)
    logger.info(f"2. 映射到工具: {selected_tool.name}")
    
    # 3. 使用LangChain工具执行任务
    if hasattr(selected_tool, '_run'):
        if selected_tool.name == "compare_etfs":
            # 提取ETF代码并进行比较
            etf_codes = ["510300", "510500"]  # 这里是从问题中提取的
            result = selected_tool._run(etf_codes=etf_codes)
            logger.info(f"3. 工具执行结果:\n{result}")
        else:
            logger.info(f"3. 工具执行结果: 非比较类工具，实际应用中会调用相应的工具")
    
    # 4. 展示如何在LangChain Agent中调用封装的原智能体
    from server.agents.langchain_agent import QuestionAnalysisTool, OutputFormatAnalysisTool
    question_tool = QuestionAnalysisTool()
    question_analysis = question_tool._run(question=user_question)
    logger.info(f"4. 调用原QuestionAgent分析: {question_analysis}")
    
    format_tool = OutputFormatAnalysisTool()
    format_analysis = format_tool._run(intent="comparison", question=user_question)
    logger.info(f"5. 调用原OutputFormatAgent分析格式: {format_analysis[:200]}...")  # 只显示前200字符
    
    logger.info("="*60)


def main():
    """主演示函数"""
    logger.info("开始LangChain Agent与原智能体集成演示")
    
    # 检查环境变量
    zhipu_api_key = os.getenv("ZHIPU_API_KEY")
    if not zhipu_api_key:
        logger.info("注意: 未配置ZHIPU_API_KEY，演示将不涉及AI生成部分")
    
    # 按顺序演示各个功能
    demo_original_agents()
    demo_langchain_tools()
    demo_rule_based_agent()
    demo_integration_flow()
    
    logger.info("演示完成! 以上展示了原智能体与LangChain Agent的完整集成方案。")


if __name__ == "__main__":
    main()