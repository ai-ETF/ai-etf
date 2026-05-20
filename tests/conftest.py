"""
共享测试 Fixtures

提供所有测试模块共用的 fixtures，包括：
- 模拟 LLM 响应
- 构造测试用状态
- Mock 工具函数
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


# ========== 状态构造 Fixtures ==========


@pytest.fixture
def sample_lyra_state():
    """
    构造一个最小可用的 LyraState 用于测试

    包含所有必需字段的默认值，各测试可按需覆盖。
    """
    from server.graphs.lyra.state import LyraState, SkillState, DataStatus

    return LyraState(
        session_id="test-session-001",
        user_id="test-user-001",
        messages=[],
        current_input="我想买沪深300",
        intent=None,
        intent_confidence=0.0,
        current_skill=None,
        skill_state=SkillState(),
        data_status=DataStatus(
            collection_id="",
            brief_ready=False,
            detail_ready=False,
            progress="0%",
        ),
        brief_data=None,
        detail_data=None,
        xiaoyan_request_id=None,
        emotion_flags=[],
        emotion_intervened=False,
        response=None,
        exec_plan_path=None,
        should_end=False,
        waiting_for_user=False,
        error=None,
        interrupt_metadata=None,
    )


@pytest.fixture
def sample_buy_decision_state(sample_lyra_state):
    """
    构造一个带有 buy_decision skill 状态的 LyraState

    模拟用户已经进入买入决策流程的场景。
    """
    from server.graphs.lyra.workflows.buy_decision.state import (
        BuyDecisionSkillState,
        InquiryAnswers,
    )

    state = dict(sample_lyra_state)
    state["current_skill"] = "buy_decision"
    state["intent"] = "buy_decision"
    state["intent_confidence"] = 0.9
    state["skill_state"] = {
        "current_step": "buy_decision",
        "extra": BuyDecisionSkillState(
            targets=["沪深300", "中证500"],
            intent_route="deep",
            inquiry_step=1,
            inquiry_answers=InquiryAnswers(),
            target_understanding_given=False,
            post_buy_rules={},
            selected_target=None,
            position_size=None,
            build_method=None,
            timing=None,
            decision_reason=None,
            skip_remaining_inquiry=False,
            user_impatient=False,
        ),
    }
    return state


# ========== LLM Mock Fixtures ==========


@pytest.fixture
def mock_llm_response():
    """
    工厂 fixture：构造模拟的 LLM 响应对象

    用法：
        response = mock_llm_response("buy_decision")
        mock_ainvoke.return_value = response
    """
    def _make_response(content: str = "", tool_calls: list = None):
        mock = MagicMock()
        mock.content = content
        mock.tool_calls = tool_calls or []
        return mock
    return _make_response


@pytest.fixture
def mock_tool_call_response():
    """
    工厂 fixture：构造模拟的 tool calling 响应

    模拟 LLM 通过 bind_tools 选择了一个工具的场景。
    """
    def _make_response(tool_name: str, tool_args: dict = None):
        mock = MagicMock()
        mock.content = ""
        mock.tool_calls = [{
            "name": tool_name,
            "args": tool_args or {},
            "id": "call_test_001",
        }]
        return mock
    return _make_response
