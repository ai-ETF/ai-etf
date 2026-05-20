"""
run_lyra 函数 interrupt/resume 测试

测试 server.graphs.lyra.graph.run_lyra() 的中断恢复机制。

run_lyra 是莱拉图的入口函数，支持两种执行模式：
1. 正常模式：创建初始状态 → ainvoke
2. 恢复模式：检测 pending interrupt → ainvoke(Command(resume=user_input))

测试覆盖：
- 正常执行（无 pending interrupt）
- 恢复执行（有 pending interrupt）
- 返回值包含 _interrupted 和 _waiting_for_input
- aget_state 检查 interrupt 状态

注意：这些测试 mock 了整个 graph 对象，测试的是 run_lyra 的调度逻辑，
不是图本身的执行。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRunLyra:
    """run_lyra 函数测试集"""

    @pytest.mark.asyncio
    async def test_normal_execution_no_interrupt(self):
        """
        无 pending interrupt 时：
        - 应创建初始状态并调用 ainvoke(initial_state)
        - 不应使用 Command(resume=...)
        """
        # Mock graph 对象
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {"response": "你好", "should_end": False}

        # Mock aget_state 返回无 pending interrupt 的快照
        mock_snapshot = MagicMock()
        mock_snapshot.next = ()  # 空 tuple = 无等待节点
        mock_graph.aget_state.return_value = mock_snapshot

        with patch("server.graphs.lyra.graph.get_lyra_graph", return_value=mock_graph):
            from server.graphs.lyra.graph import run_lyra
            result = await run_lyra("user-001", "session-001", "你好")

        # ainvoke 应被调用（不是 Command 模式）
        mock_graph.ainvoke.assert_called()
        call_args = mock_graph.ainvoke.call_args
        # 第一个参数应该是 LyraState dict（不是 Command）
        first_arg = call_args[0][0]
        assert isinstance(first_arg, dict), f"第一个参数应是 state dict，实际类型: {type(first_arg)}"
        assert first_arg.get("current_input") == "你好", f"current_input 应为 '你好'"
        print(f"[DEBUG] 正常模式: ainvoke 参数 current_input='{first_arg.get('current_input')}'")

    @pytest.mark.asyncio
    async def test_resume_from_interrupt(self):
        """
        有 pending interrupt 时：
        - 应使用 Command(resume=user_input) 调用 ainvoke
        - 不应创建新的初始状态
        """
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {"response": "你的投资目标是什么？", "should_end": False}

        # 模拟两次 aget_state：
        # 第一次：有 pending interrupt（snapshot.next 非空）
        # 第二次：检查执行后状态
        mock_snapshot_pending = MagicMock()
        mock_snapshot_pending.next = ("inquiry_chain",)  # inquiry_chain 节点在等待

        mock_snapshot_done = MagicMock()
        mock_snapshot_done.next = ()  # 执行完毕

        mock_graph.aget_state.side_effect = [mock_snapshot_pending, mock_snapshot_done]

        with patch("server.graphs.lyra.graph.get_lyra_graph", return_value=mock_graph), \
             patch("server.graphs.lyra.graph.Command") as mock_command_cls:
            # Mock Command 构造
            mock_command = MagicMock()
            mock_command_cls.return_value = mock_command

            from server.graphs.lyra.graph import run_lyra
            result = await run_lyra("user-001", "session-001", "我想长期配置")

        # Command 应该被创建，参数为 resume=user_input
        mock_command_cls.assert_called_once_with(resume="我想长期配置")
        print(f"[DEBUG] 恢复模式: Command(resume='我想长期配置')")

        # ainvoke 应该用 Command 对象调用
        mock_graph.ainvoke.assert_called_once()
        call_args = mock_graph.ainvoke.call_args
        assert call_args[0][0] is mock_command, "ainvoke 第一个参数应为 Command 对象"
        print(f"[DEBUG] ainvoke 使用 Command 对象 ✓")

    @pytest.mark.asyncio
    async def test_returns_interrupted_flag(self):
        """
        执行后如果有新的 interrupt，返回值应包含 _interrupted=True
        """
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {"response": "问题", "should_end": False}

        # 两次 aget_state：第一次无 pending，第二次有新 interrupt
        mock_snapshot_no_pending = MagicMock()
        mock_snapshot_no_pending.next = ()

        mock_snapshot_new_interrupt = MagicMock()
        mock_snapshot_new_interrupt.next = ("inquiry_chain",)

        mock_graph.aget_state.side_effect = [mock_snapshot_no_pending, mock_snapshot_new_interrupt]

        with patch("server.graphs.lyra.graph.get_lyra_graph", return_value=mock_graph):
            from server.graphs.lyra.graph import run_lyra
            result = await run_lyra("user-001", "session-001", "测试")

        assert result.get("_interrupted") is True, f"_interrupted 应为 True，实际: {result.get('_interrupted')}"
        assert result.get("_waiting_for_input") is True, f"_waiting_for_input 应为 True"
        print(f"[DEBUG] _interrupted={result.get('_interrupted')}, _waiting_for_input={result.get('_waiting_for_input')}")

    @pytest.mark.asyncio
    async def test_returns_no_interrupt_when_done(self):
        """
        执行后无 interrupt，返回值应包含 _interrupted=False
        """
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {"response": "再见", "should_end": True}

        mock_snapshot = MagicMock()
        mock_snapshot.next = ()
        mock_graph.aget_state.return_value = mock_snapshot

        with patch("server.graphs.lyra.graph.get_lyra_graph", return_value=mock_graph):
            from server.graphs.lyra.graph import run_lyra
            result = await run_lyra("user-001", "session-001", "结束")

        assert result.get("_interrupted") is False, f"_interrupted 应为 False"
        assert result.get("_waiting_for_input") is False, f"_waiting_for_input 应为 False"
        print(f"[DEBUG] 对话结束: _interrupted=False, _waiting_for_input=False")

    @pytest.mark.asyncio
    async def test_config_contains_thread_id(self):
        """
        ainvoke 的 config 应包含正确的 thread_id（等于 session_id）
        """
        mock_graph = AsyncMock()
        mock_graph.ainvoke.return_value = {"response": "ok"}

        mock_snapshot = MagicMock()
        mock_snapshot.next = ()
        mock_graph.aget_state.return_value = mock_snapshot

        with patch("server.graphs.lyra.graph.get_lyra_graph", return_value=mock_graph):
            from server.graphs.lyra.graph import run_lyra
            await run_lyra("user-001", "my-session-123", "测试")

        # 检查 config 参数
        call_kwargs = mock_graph.ainvoke.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("config")
        assert config["configurable"]["thread_id"] == "my-session-123", (
            f"thread_id 应为 'my-session-123'，实际: {config['configurable']['thread_id']}"
        )
        print(f"[DEBUG] config.thread_id = '{config['configurable']['thread_id']}'")
