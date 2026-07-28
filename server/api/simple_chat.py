"""
简单对话 API

接收前端问题，调用 LLM，SSE 流式返回回答。
无对话历史、无会话管理，单轮对话。
"""
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from server.llm import get_llm
from server.utils.sse import format_sse_event, create_sse_stream_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simple-chat", tags=["simple-chat"])


# ========== 请求模型 ==========


class SimpleChatRequest(BaseModel):
    """简单对话请求"""
    question: str = Field(..., description="用户问题")


# ========== 流式生成器 ==========


async def stream_simple_chat(question: str):
    """
    流式调用 LLM，逐 token 输出。

    Args:
        question: 用户问题

    Yields:
        SSE 格式的事件字符串
    """
    from langchain_core.messages import HumanMessage

    llm = get_llm()

    try:
        async for chunk in llm.astream([HumanMessage(content=question)]):
            if chunk.content:
                yield format_sse_event("token", {"content": chunk.content})

        yield format_sse_event("done", {})

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        yield format_sse_event("error", {"message": str(e)})


# ========== API 端点 ==========


@router.post("")
async def simple_chat(req: SimpleChatRequest):
    """
    SSE 流式对话端点

    事件类型：
    - token: LLM 生成的 token
    - done: 生成结束
    - error: 错误
    """
    return create_sse_stream_response(
        generator=stream_simple_chat(req.question),
        session_id="simple",
    )
