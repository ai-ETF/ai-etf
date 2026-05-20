"""
意图识别节点测试

测试 server.graphs.lyra.nodes.classify_intent_node() 函数。

该节点使用两层路由：
1. 快速通道：关键词匹配（SkillRegistry.select_skill）
2. LLM tool calling：通过 bind_tools 让 LLM 选择意图工具

测试覆盖：
- 关键词快速通道命中（跳过 LLM）
- 关键词未命中时走 tool calling
- tool calling 返回有效 tool_calls
- tool calling 无 tool_calls 时降级为 unknown
- LLM 异常时降级为 unknown

Mock 策略：
- patch("server.graphs.lyra.nodes.get_skill_registry") — 模拟关键词匹配
- patch("server.graphs.lyra.nodes.get_llm_with_tools") — 模拟 LLM tool calling
  （函数内部通过 `from server.llm import get_llm_with_tools` 导入，需要 patch 使用处）
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestClassifyIntentNode:
    """classify_intent_node 测试集"""

    @pytest.mark.asyncio
    async def test_keyword_fast_path(self, sample_lyra_state):
        """关键词匹配成功时，应直接返回结果，不调用 LLM"""
        state = dict(sample_lyra_state)
        state["current_input"] = "我想买沪深300"

        mock_metadata = MagicMock()
        mock_metadata.name = "buy-decision"

        with patch("server.graphs.lyra.nodes.get_skill_registry") as mock_registry:
            mock_registry.return_value.select_skill.return_value = mock_metadata

            from server.graphs.lyra.nodes import classify_intent_node
            result = await classify_intent_node(state)

        assert result["intent"] == "buy-decision", f"intent 应为 'buy-decision'，实际: {result.get('intent')}"
        assert result["intent_confidence"] == 0.9, f"confidence 应为 0.9，实际: {result.get('intent_confidence')}"
        assert result["current_skill"] == "buy-decision"
        print(f"[DEBUG] 关键词快速通道: intent={result['intent']}, confidence={result['intent_confidence']}")

    @pytest.mark.asyncio
    async def test_tool_calling_path(self, sample_lyra_state, mock_tool_call_response):
        """关键词未命中时，应走 LLM tool calling 路径"""
        state = dict(sample_lyra_state)
        state["current_input"] = "帮我看看半导体ETF"

        mock_response = mock_tool_call_response("buy_decision", {"targets": "半导体"})

        # 关键：patch get_llm_with_tools 而不是 ChatAnthropic
        # 因为 _llm_classify_intent_with_tools 内部调用 get_llm_with_tools(INTENT_TOOLS)
        mock_bound_llm = AsyncMock()
        mock_bound_llm.ainvoke.return_value = mock_response

        with patch("server.graphs.lyra.nodes.get_skill_registry") as mock_registry, \
             patch("server.graphs.lyra.nodes.get_llm_with_tools", return_value=mock_bound_llm):
            mock_registry.return_value.select_skill.return_value = None

            from server.graphs.lyra.nodes import classify_intent_node
            result = await classify_intent_node(state)

        assert result["intent"] == "buy_decision", f"intent 应为 'buy_decision'，实际: {result.get('intent')}"
        assert result["intent_confidence"] == 1.0, f"tool calling 置信度应为 1.0，实际: {result.get('intent_confidence')}"
        print(f"[DEBUG] tool calling 路径: intent={result['intent']}, confidence={result['intent_confidence']}")

    @pytest.mark.asyncio
    async def test_tool_calling_no_tool_calls(self, sample_lyra_state):
        """LLM 未选择任何工具时，应降级为 unknown"""
        state = dict(sample_lyra_state)
        state["current_input"] = "随便聊聊"

        mock_response = MagicMock()
        mock_response.content = "我不确定你的意图"
        mock_response.tool_calls = []

        mock_bound_llm = AsyncMock()
        mock_bound_llm.ainvoke.return_value = mock_response

        with patch("server.graphs.lyra.nodes.get_skill_registry") as mock_registry, \
             patch("server.graphs.lyra.nodes.get_llm_with_tools", return_value=mock_bound_llm):
            mock_registry.return_value.select_skill.return_value = None

            from server.graphs.lyra.nodes import classify_intent_node
            result = await classify_intent_node(state)

        assert result["intent"] == "unknown", f"无 tool_calls 应降级为 unknown，实际: {result.get('intent')}"
        assert result["intent_confidence"] == 0.3, f"unknown 置信度应为 0.3，实际: {result.get('intent_confidence')}"
        print(f"[DEBUG] 无 tool_calls: intent={result['intent']}, confidence={result['intent_confidence']}")

    @pytest.mark.asyncio
    async def test_llm_exception_fallback(self, sample_lyra_state):
        """LLM 调用异常时，应降级为 unknown"""
        state = dict(sample_lyra_state)
        state["current_input"] = "测试异常"

        mock_bound_llm = AsyncMock()
        mock_bound_llm.ainvoke.side_effect = Exception("API 调用失败")

        with patch("server.graphs.lyra.nodes.get_skill_registry") as mock_registry, \
             patch("server.graphs.lyra.nodes.get_llm_with_tools", return_value=mock_bound_llm):
            mock_registry.return_value.select_skill.return_value = None

            from server.graphs.lyra.nodes import classify_intent_node
            result = await classify_intent_node(state)

        assert result["intent"] == "unknown", f"异常时应降级为 unknown，实际: {result.get('intent')}"
        print(f"[DEBUG] LLM 异常: intent={result['intent']}")

    @pytest.mark.asyncio
    async def test_all_intent_tools_routed(self, sample_lyra_state, mock_tool_call_response):
        """验证每个 tool name 都能正确映射到 intent"""
        from server.graphs.lyra.tools import TOOL_NAME_TO_INTENT

        for tool_name, expected_intent in TOOL_NAME_TO_INTENT.items():
            state = dict(sample_lyra_state)
            state["current_input"] = f"测试 {tool_name}"

            mock_response = mock_tool_call_response(tool_name)
            mock_bound_llm = AsyncMock()
            mock_bound_llm.ainvoke.return_value = mock_response

            with patch("server.graphs.lyra.nodes.get_skill_registry") as mock_registry, \
                 patch("server.graphs.lyra.nodes.get_llm_with_tools", return_value=mock_bound_llm):
                mock_registry.return_value.select_skill.return_value = None

                from server.graphs.lyra.nodes import classify_intent_node
                result = await classify_intent_node(state)

            assert result["intent"] == expected_intent, (
                f"tool '{tool_name}' 应映射到 intent '{expected_intent}'，实际: {result.get('intent')}"
            )
            print(f"[DEBUG] tool '{tool_name}' → intent '{result['intent']}' ✓")
