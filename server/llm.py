"""
统一 LLM 服务

所有节点通过此模块获取 LLM 实例，避免各处重复创建 ChatAnthropic。
"""
from typing import AsyncIterator, Sequence

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from server.config.settings import SETTINGS

_llm_instance: ChatAnthropic | None = None


def get_llm() -> ChatAnthropic:
    """
    获取共享的 LLM 实例（单例模式）

    单例模式：整个应用只创建一个 LLM 客户端，所有节点共享同一个实例。
    好处：避免重复创建连接、节省资源、保持一致的配置。

    为什么用 global？
        Python 函数内赋值会创建局部变量。要修改模块级的 _llm_instance，
        必须用 global 声明，否则 Python 会报错 UnboundLocalError。

    返回值：
        ChatAnthropic 实例（LangChain 对 Anthropic API 的封装）
        调用方通过 .invoke() / .ainvoke() 发送消息给 LLM
    """
    global _llm_instance

    # 首次调用时创建实例，后续调用直接返回已有的实例
    if _llm_instance is None:
        _llm_instance = ChatAnthropic(
            model=SETTINGS.LYRA_MODEL,       # 模型名称，如 "claude-sonnet-4-20250514"
            max_tokens=SETTINGS.LYRA_MAX_TOKENS,  # 单次回复最大 token 数
            api_key=SETTINGS.ANTHROPIC_API_KEY,    # API 密钥，从环境变量读取
        )

    return _llm_instance


def get_llm_with_tools(tools: list) -> ChatAnthropic:
    """获取绑定了工具的 LLM 实例（不缓存，因为 tools 可能变化）"""
    return get_llm().bind_tools(tools)


async def astream_text(
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
) -> AsyncIterator[str]:
    """
    流式调用 LLM，逐段产出纯文本。

    归一 AIMessageChunk.content（str 或 content-block 列表）：
    - str → 原样产出
    - list → 仅取 type == "text" 的块（thinking 等非文本块丢弃）

    背景：langchain-anthropic 对含 tools / thinking / 推理增量的事件会把
    content 包成 [{type: 'text'|'thinking', ...}] 这类列表而非纯字符串，
    直接 `str += chunk.content` 会抛 TypeError。统一在此抽取纯文本。

    典型用法：
        async for text in astream_text(llm, [HumanMessage(content=question)]):
            ...   # 落库端自行拼接，回显端直接转发
    """
    async for chunk in llm.astream(messages):
        content = chunk.content
        if isinstance(content, str):
            if content:
                yield content
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    yield text
