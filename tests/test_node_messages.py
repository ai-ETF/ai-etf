"""
节点消息去重测试

测试 entry_node 和 output_node 的消息去重逻辑。

背景：多轮对话时，图会循环执行 entry → ... → save_state → entry。
如果 current_input 不变（interrupt 场景），entry_node 不应重复添加消息。
同理，output_node 不应重复追加相同的 response。

测试覆盖：
- entry_node 首次添加消息
- entry_node 重复输入不添加
- output_node 首次追加响应
- output_node 重复响应不追加
"""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import HumanMessage, AIMessage


class TestEntryNodeMessageDedup:
    """entry_node 消息去重测试"""

    @pytest.mark.asyncio
    async def test_first_input_adds_message(self, sample_lyra_state):
        """首次输入应添加 HumanMessage 到消息列表"""
        state = dict(sample_lyra_state)
        state["messages"] = []
        state["current_input"] = "你好"

        with patch("server.graphs.lyra.nodes._extract_targets", return_value=[]):
            from server.graphs.lyra.nodes import entry_node
            result = await entry_node(state)

        messages = result["messages"]
        assert len(messages) == 1, f"应有 1 条消息，实际: {len(messages)}"
        assert messages[0].content == "你好", f"消息内容应为 '你好'，实际: {messages[0].content}"
        print(f"[DEBUG] 首次输入: messages 长度={len(messages)}, 内容='{messages[0].content}'")

    @pytest.mark.asyncio
    async def test_duplicate_input_not_added(self, sample_lyra_state):
        """重复的输入不应被添加到消息列表"""
        state = dict(sample_lyra_state)
        # 模拟消息列表中已有 "你好"
        state["messages"] = [HumanMessage(content="你好")]
        state["current_input"] = "你好"  # 相同的输入

        with patch("server.graphs.lyra.nodes._extract_targets", return_value=[]):
            from server.graphs.lyra.nodes import entry_node
            result = await entry_node(state)

        messages = result["messages"]
        assert len(messages) == 1, f"重复输入不应添加，应有 1 条，实际: {len(messages)}"
        print(f"[DEBUG] 重复输入: messages 长度={len(messages)}（未重复添加）✓")

    @pytest.mark.asyncio
    async def test_different_input_adds_message(self, sample_lyra_state):
        """不同的输入应正常添加"""
        state = dict(sample_lyra_state)
        state["messages"] = [HumanMessage(content="你好")]
        state["current_input"] = "我想买沪深300"  # 不同的输入

        with patch("server.graphs.lyra.nodes._extract_targets", return_value=["沪深300"]):
            from server.graphs.lyra.nodes import entry_node
            result = await entry_node(state)

        messages = result["messages"]
        assert len(messages) == 2, f"不同输入应添加，应有 2 条，实际: {len(messages)}"
        assert messages[1].content == "我想买沪深300"
        print(f"[DEBUG] 不同输入: messages 长度={len(messages)} ✓")


class TestOutputNodeMessageDedup:
    """output_node 消息去重测试"""

    @pytest.mark.asyncio
    async def test_first_response_adds_message(self, sample_lyra_state):
        """首次响应应添加 AIMessage"""
        state = dict(sample_lyra_state)
        state["messages"] = [HumanMessage(content="你好")]
        state["response"] = "你好！有什么可以帮你的？"

        from server.graphs.lyra.nodes import output_node
        result = await output_node(state)

        messages = result["messages"]
        assert len(messages) == 2, f"应有 2 条消息，实际: {len(messages)}"
        assert isinstance(messages[-1], AIMessage), f"最后一条应是 AIMessage"
        print(f"[DEBUG] 首次响应: messages 长度={len(messages)} ✓")

    @pytest.mark.asyncio
    async def test_duplicate_response_not_added(self, sample_lyra_state):
        """相同的响应不应重复追加"""
        state = dict(sample_lyra_state)
        # 消息列表最后一条已经是这个响应
        state["messages"] = [
            HumanMessage(content="你好"),
            AIMessage(content="你好！有什么可以帮你的？"),
        ]
        state["response"] = "你好！有什么可以帮你的？"  # 相同的响应

        from server.graphs.lyra.nodes import output_node
        result = await output_node(state)

        messages = result["messages"]
        assert len(messages) == 2, f"重复响应不应追加，应有 2 条，实际: {len(messages)}"
        print(f"[DEBUG] 重复响应: messages 长度={len(messages)}（未重复追加）✓")

    @pytest.mark.asyncio
    async def test_none_response_generates_default(self, sample_lyra_state):
        """response=None 时应生成默认回复"""
        state = dict(sample_lyra_state)
        state["messages"] = []
        state["response"] = None
        state["intent"] = "unknown"

        from server.graphs.lyra.nodes import output_node
        result = await output_node(state)

        assert result["response"] is not None, "应生成默认回复"
        assert "学习" in result["response"] or "试试" in result["response"], (
            f"unknown 意图的默认回复应包含引导内容，实际: {result['response'][:50]}"
        )
        print(f"[DEBUG] None response → 默认回复: '{result['response'][:50]}...'")
