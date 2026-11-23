"""astream_text 单元测试：LLM 流式 chunk.content 归一化。

背景：langchain-anthropic 对含 tools / thinking / 推理增量的事件会把
content 包成 [{type:'text'|'thinking', ...}] 列表而非纯字符串，直接
`str += chunk.content` 会抛 TypeError（曾致线上推理模型流式崩溃）。
astream_text 通过参数注入 llm，测试用 FakeLLM 替身覆盖三种形态，
全程不联网、不调用真实模型。
"""
import pytest

from server.llm import astream_text


class FakeChunk:
    """模拟真实 LLM 流出的一个碎片，只暴露 .content 字段。"""

    def __init__(self, content):
        self.content = content


class FakeLLM:
    """模拟真实 LLM 的 .astream() 流式接口（替身演员）。"""

    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, messages):
        for c in self._chunks:
            yield c


async def _collect(llm) -> list[str]:
    """把 astream_text 吐出的所有文本片段收进列表。"""
    return [t async for t in astream_text(llm, [])]


@pytest.mark.asyncio
async def test_纯字符串碎片_原样拼接输出():
    llm = FakeLLM([FakeChunk("你好"), FakeChunk("！"), FakeChunk("有什么")])
    assert await _collect(llm) == ["你好", "！", "有什么"]


@pytest.mark.asyncio
async def test_text块_逐块输出():
    llm = FakeLLM([
        FakeChunk([{"type": "text", "text": "你好"}]),
        FakeChunk([{"type": "text", "text": "！"}]),
    ])
    assert await _collect(llm) == ["你好", "！"]


@pytest.mark.asyncio
async def test_thinking块被丢弃_只留text():
    """复刻线上崩溃场景：content 为 dict 列表，thinking 须丢弃且不崩溃。"""
    llm = FakeLLM([FakeChunk([
        {"type": "thinking", "thinking": "内部推理过程"},
        {"type": "text", "text": "答案"},
    ])])
    assert await _collect(llm) == ["答案"]


@pytest.mark.asyncio
async def test_空内容不产出():
    llm = FakeLLM([
        FakeChunk(""),
        FakeChunk([{"type": "text", "text": ""}]),
    ])
    assert await _collect(llm) == []
