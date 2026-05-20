"""
追问链 interrupt 模式测试

测试 server.graphs.lyra.workflows.buy_decision.nodes.inquiry_chain_node() 中
使用 LangGraph interrupt() 原语的多轮问答机制。

interrupt 模式工作原理：
1. 节点生成第一个问题，返回 state（包含 response）
2. 图继续执行到 save_state → should_end → continue → entry（循环回来）
3. 再次进入 inquiry_chain_node 时，step > 1，调用 interrupt() 暂停
4. 用户回复后，Command(resume=answer) 恢复，interrupt() 返回用户回答
5. 节点记录回答，生成下一个问题，重复 3-4

测试覆盖：
- 首次进入（step=1）：生成问题，不调用 interrupt
- 后续步骤（step>1）：调用 interrupt 获取用户回答
- 回答记录正确性
- 步骤推进逻辑
- 跳过追问链（skip_remaining_inquiry）

所有 LLM 调用和 interrupt 都被 mock。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestInquiryChainNode:
    """inquiry_chain_node 测试集"""

    @pytest.mark.asyncio
    async def test_first_step_generates_question(self, sample_buy_decision_state):
        """
        首次进入追问链（step=1）时：
        - 应生成第一个问题（投资目标）
        - 不应调用 interrupt()
        - inquiry_step 应推进到 2
        """
        state = dict(sample_buy_decision_state)
        # step=1 是初始状态（来自 fixture）

        # Mock LLM 返回一个追问
        mock_llm_response = MagicMock()
        mock_llm_response.content = "你这次想买沪深300，主要是出于什么考虑？"

        with patch("server.graphs.lyra.workflows.buy_decision.nodes.get_llm") as mock_get_llm, \
             patch("server.graphs.lyra.workflows.buy_decision.nodes._get_skill_loader") as mock_loader:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_llm_response
            mock_get_llm.return_value = mock_llm

            # Mock SkillLoader 返回 inquiry 指南
            mock_loader_instance = MagicMock()
            mock_loader_instance.load_reference.return_value = "追问链指南内容"
            mock_loader.return_value = mock_loader_instance

            from server.graphs.lyra.workflows.buy_decision.nodes import inquiry_chain_node
            result = await inquiry_chain_node(state)

        # 应返回生成的问题
        assert result["response"] is not None, "应返回追问内容"
        assert "考虑" in result["response"] or "买" in result["response"], (
            f"追问应包含投资目标相关内容，实际: {result['response'][:50]}"
        )

        # skill_state 应更新 inquiry_step
        skill_state = result.get("skill_state", {}).get("extra", {})
        assert skill_state.get("inquiry_step") == 2, (
            f"inquiry_step 应推进到 2，实际: {skill_state.get('inquiry_step')}"
        )
        print(f"[DEBUG] step=1: response='{result['response'][:60]}...', step→{skill_state.get('inquiry_step')}")

    @pytest.mark.asyncio
    async def test_second_step_records_answer_and_generates_next(self, sample_buy_decision_state):
        """
        第二步（step=2）时：
        - 应调用 interrupt() 获取用户对 step 1 的回答
        - 记录回答到 inquiry_answers
        - 生成第二个问题（投资期限）
        - step 推进到 3（含标的理解插入）
        """
        state = dict(sample_buy_decision_state)
        # 设置 step=2（模拟已经问过第一个问题）
        state["skill_state"]["extra"]["inquiry_step"] = 2

        # Mock interrupt 返回用户的回答
        mock_user_answer = "我想长期配置，闲钱投资"

        # Mock LLM 返回追问
        mock_llm_response = MagicMock()
        mock_llm_response.content = "你打算这笔钱投多久？"

        with patch("server.graphs.lyra.workflows.buy_decision.nodes.get_llm") as mock_get_llm, \
             patch("server.graphs.lyra.workflows.buy_decision.nodes._get_skill_loader") as mock_loader, \
             patch("server.graphs.lyra.workflows.buy_decision.nodes.interrupt", return_value=mock_user_answer) as mock_interrupt:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_llm_response
            mock_get_llm.return_value = mock_llm

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_reference.return_value = "追问链指南内容"
            mock_loader.return_value = mock_loader_instance

            from server.graphs.lyra.workflows.buy_decision.nodes import inquiry_chain_node
            result = await inquiry_chain_node(state)

        # interrupt 应被调用一次
        mock_interrupt.assert_called_once()
        interrupt_arg = mock_interrupt.call_args[0][0]
        assert interrupt_arg["type"] == "inquiry_wait", f"interrupt 参数应包含 type='inquiry_wait'，实际: {interrupt_arg}"
        print(f"[DEBUG] interrupt 调用参数: {interrupt_arg}")

        # 用户回答应被记录到 inquiry_answers
        skill_state = result.get("skill_state", {}).get("extra", {})
        answers = skill_state.get("inquiry_answers", {})
        assert answers.get("goal") == mock_user_answer, (
            f"step 1 的回答应记录为 goal，实际: {answers.get('goal')}"
        )
        print(f"[DEBUG] step=2: 记录回答 goal='{answers.get('goal')}'")

        # step 应推进到 3（step 2 后插入标的理解）
        assert skill_state.get("inquiry_step") == 3, (
            f"step 2 后应推进到 3（含标的理解），实际: {skill_state.get('inquiry_step')}"
        )
        print(f"[DEBUG] step=2: step→{skill_state.get('inquiry_step')}, response='{result['response'][:60]}...'")

    @pytest.mark.asyncio
    async def test_skip_inquiry(self, sample_buy_decision_state):
        """
        设置 skip_remaining_inquiry=True 时：
        - 应跳过追问链，直接到详细报告
        - 不应调用 interrupt()
        """
        state = dict(sample_buy_decision_state)
        state["skill_state"]["extra"]["skip_remaining_inquiry"] = True

        # Mock LLM（output_detail_report_node 不调用 LLM，但需要 mock loader）
        with patch("server.graphs.lyra.workflows.buy_decision.nodes._get_skill_loader") as mock_loader, \
             patch("server.graphs.lyra.workflows.buy_decision.nodes._skip_to_detail_report") as mock_skip:
            mock_skip.return_value = {"response": "跳过追问，直接输出详细报告"}

            from server.graphs.lyra.workflows.buy_decision.nodes import inquiry_chain_node
            result = await inquiry_chain_node(state)

        # 应调用跳过函数
        mock_skip.assert_called_once()
        print(f"[DEBUG] skip_remaining_inquiry=True → 跳过追问链")

    @pytest.mark.asyncio
    async def test_no_waiting_for_user_in_return(self, sample_buy_decision_state):
        """
        返回值中不应包含 waiting_for_user（已改用 interrupt 模式）
        """
        state = dict(sample_buy_decision_state)

        mock_llm_response = MagicMock()
        mock_llm_response.content = "测试问题"

        with patch("server.graphs.lyra.workflows.buy_decision.nodes.get_llm") as mock_get_llm, \
             patch("server.graphs.lyra.workflows.buy_decision.nodes._get_skill_loader") as mock_loader:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = mock_llm_response
            mock_get_llm.return_value = mock_llm

            mock_loader_instance = MagicMock()
            mock_loader_instance.load_reference.return_value = "指南"
            mock_loader.return_value = mock_loader_instance

            from server.graphs.lyra.workflows.buy_decision.nodes import inquiry_chain_node
            result = await inquiry_chain_node(state)

        assert "waiting_for_user" not in result, (
            f"返回值不应包含 waiting_for_user（已改用 interrupt），实际 keys: {result.keys()}"
        )
        print(f"[DEBUG] 返回值 keys: {list(result.keys())} — 无 waiting_for_user ✓")
