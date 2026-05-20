"""
意图路由 Tools 测试

测试 server.graphs.lyra.tools.py 中定义的 LangChain Tools。

测试覆盖：
- 所有 5 个 tool 函数可正常调用
- TOOL_NAME_TO_INTENT 映射完整性
- INTENT_TOOLS 列表完整性
- Tool 的 name 属性与映射一致
"""
from server.graphs.lyra.tools import (
    buy_decision,
    position_manage,
    stop_loss,
    knowledge_qa,
    market_analysis,
    INTENT_TOOLS,
    TOOL_NAME_TO_INTENT,
)


class TestToolDefinitions:
    """Tool 定义测试集"""

    def test_buy_decision_tool_callable(self):
        """buy_decision tool 应可正常调用并返回预期格式"""
        result = buy_decision.invoke({"targets": "沪深300"})
        assert "buy_decision" in result, f"返回值应包含 'buy_decision'，实际: {result}"
        assert "沪深300" in result, f"返回值应包含目标名称，实际: {result}"
        print(f"[DEBUG] buy_decision.invoke('沪深300') → {result}")

    def test_position_manage_tool_callable(self):
        """position_manage tool 应可正常调用"""
        result = position_manage.invoke({"action": "加仓"})
        assert "position_manage" in result
        print(f"[DEBUG] position_manage.invoke('加仓') → {result}")

    def test_stop_loss_tool_callable(self):
        """stop_loss tool 应可正常调用"""
        result = stop_loss.invoke({"action": "止盈"})
        assert "stop_loss" in result
        print(f"[DEBUG] stop_loss.invoke('止盈') → {result}")

    def test_knowledge_qa_tool_callable(self):
        """knowledge_qa tool 应可正常调用"""
        result = knowledge_qa.invoke({"question": "什么是ETF"})
        assert "knowledge_qa" in result
        print(f"[DEBUG] knowledge_qa.invoke('什么是ETF') → {result}")

    def test_market_analysis_tool_callable(self):
        """market_analysis tool 应可正常调用"""
        result = market_analysis.invoke({"topic": "最近行情"})
        assert "market_analysis" in result
        print(f"[DEBUG] market_analysis.invoke('最近行情') → {result}")


class TestToolMapping:
    """Tool 映射完整性测试"""

    def test_intent_tools_list_length(self):
        """INTENT_TOOLS 应包含 5 个工具"""
        assert len(INTENT_TOOLS) == 5, f"应有 5 个工具，实际: {len(INTENT_TOOLS)}"
        print(f"[DEBUG] INTENT_TOOLS 数量: {len(INTENT_TOOLS)}")

    def test_tool_name_to_intent_completeness(self):
        """TOOL_NAME_TO_INTENT 应覆盖所有 5 个意图"""
        expected_intents = {"buy_decision", "position_manage", "stop_loss", "knowledge_qa", "market_analysis"}
        actual_intents = set(TOOL_NAME_TO_INTENT.values())
        assert expected_intents == actual_intents, (
            f"意图映射不完整。\n"
            f"  期望: {expected_intents}\n"
            f"  实际: {actual_intents}"
        )
        print(f"[DEBUG] TOOL_NAME_TO_INTENT 映射: {TOOL_NAME_TO_INTENT}")

    def test_tool_names_match_mapping_keys(self):
        """每个 tool 的 .name 属性应与 TOOL_NAME_TO_INTENT 的 key 一致"""
        for tool in INTENT_TOOLS:
            assert tool.name in TOOL_NAME_TO_INTENT, (
                f"Tool '{tool.name}' 不在 TOOL_NAME_TO_INTENT 映射中"
            )
            print(f"[DEBUG] tool.name='{tool.name}' → intent='{TOOL_NAME_TO_INTENT[tool.name]}'")

    def test_tool_docstrings_not_empty(self):
        """每个 tool 的 docstring（LLM 选择依据）不应为空"""
        for tool in INTENT_TOOLS:
            assert tool.description, f"Tool '{tool.name}' 的 description 为空"
            print(f"[DEBUG] tool '{tool.name}' description 长度: {len(tool.description)}")
