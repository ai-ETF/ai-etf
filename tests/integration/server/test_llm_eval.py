"""P2-10 LLM 交互 eval 测试：真实 Anthropic 流式。

模块名称：LLM 服务（get_llm + astream_text）
所测功能：真实 ChatAnthropic 创建 + 流式 chunk 归一化（str / content-block 列表）
使用的测试方法：真实 Anthropic API（eval marker，默认不跑，需 .env 配置 ANTHROPIC_API_KEY）
"""
import asyncio

import pytest

pytestmark = pytest.mark.eval


@pytest.fixture
def real_llm():
    """真实 ChatAnthropic 实例。

    conftest 为加速 API 测试把 langchain_anthropic 替身成了空类，此处移除替身、
    加载真实依赖（>60s），再让 server.llm 重新以真实 ChatAnthropic 加载。
    """
    from dotenv import load_dotenv

    load_dotenv()

    from server.config.settings import SETTINGS

    if not SETTINGS.ANTHROPIC_API_KEY:
        pytest.skip("需在 .env 配置 ANTHROPIC_API_KEY")

    import sys

    sys.modules.pop("langchain_anthropic", None)
    sys.modules.pop("server.llm", None)

    from server.llm import get_llm

    return get_llm()


def test_get_llm_创建真实client(real_llm):
    assert real_llm is not None
    assert hasattr(real_llm, "model")
    assert real_llm.model == "claude-sonnet-4-20250514"


def test_astream_text_接真实流式并归一化(real_llm):
    from server.llm import astream_text
    from langchain_core.messages import HumanMessage

    chunks = []

    async def _collect():
        async for text in astream_text(real_llm, [HumanMessage(content="用一句话介绍你自己")]):
            chunks.append(text)

    asyncio.run(_collect())
    answer = "".join(chunks)
    assert answer.strip(), "应返回非空的纯文本回答"
    # astream_text 只产出纯文本，不应混入 thinking 等非文本块
    assert "thinking" not in answer.lower()
