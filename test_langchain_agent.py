"""
测试LangChain Agent与智谱AI集成
"""

import os
import sys
from dotenv import load_dotenv

# 加载环境变量
current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(current_dir, '.env')
load_dotenv(dotenv_path=dotenv_path)

# 添加server目录到Python路径
sys.path.insert(0, os.path.join(current_dir, 'server'))

from server.services.qa_service import QAService
from server.agents.etf_rule_agent import ETFRuleBasedAgent

def test_qa_service():
    """测试QA服务功能"""
    print("开始测试QA服务...")
    
    try:
        # 创建QA服务实例
        qa_service = QAService()
        print("✓ QA服务初始化成功")
        
        # 测试问题
        test_questions = [
            "什么是沪深300ETF？",
            "比较一下510300和159915这两个ETF",
            "510300ETF的风险如何",
            "我的投资组合应该怎么调整？"
        ]
        
        print("\n开始处理测试问题:")
        for i, question in enumerate(test_questions, 1):
            print(f"\n{i}. 问题: {question}")
            try:
                result = qa_service.handle_question(question)
                print(f"   回答: {result['prompt'][:200]}...")  # 只显示前200个字符
            except Exception as e:
                print(f"   错误: {str(e)}")
        
        print("\n✓ QA服务测试完成")
        
    except Exception as e:
        print(f"✗ QA服务测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


def test_rule_agent():
    """测试规则型Agent功能"""
    print("\n开始测试规则型Agent...")
    
    try:
        rule_agent = ETFRuleBasedAgent()
        print("✓ 规则型Agent初始化成功")
        
        test_questions = [
            "什么是沪深300ETF？",
            "比较一下510300和159915这两个ETF",
            "510300ETF的风险如何",
            "我的投资组合应该怎么调整？"
        ]
        
        print("\n规则型Agent分析结果:")
        for i, question in enumerate(test_questions, 1):
            print(f"\n{i}. 问题: {question}")
            decision = rule_agent.decide_intent(question, "test_user", "test_chat")
            print(f"   意图: {decision.intent.value}")
            print(f"   工具: {decision.selected_tool}")
            print(f"   置信度: {decision.confidence}")
            print(f"   需要澄清: {decision.needs_clarification}")
        
        print("\n✓ 规则型Agent测试完成")
        
    except Exception as e:
        print(f"✗ 规则型Agent测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 检查是否设置了ZHIPU_API_KEY
    if not os.getenv("ZHIPU_API_KEY"):
        print("⚠️ 警告: 未设置ZHIPU_API_KEY环境变量，测试可能会失败")
    
    print("开始LangChain Agent与智谱AI集成测试")
    print("=" * 50)
    
    test_rule_agent()
    test_qa_service()
    
    print("\n测试完成!")