"""
消息 API

接收前端问题，自动管理会话，保存消息，流式返回 LLM 回答。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from server.llm import get_llm
from server.storage.chat_repo import get_chat_repo
from server.utils.sse import format_sse_event, create_sse_stream_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


# ========== 请求模型 ==========


class MessageRequest(BaseModel):
    """消息请求"""
    user_id: str = Field(..., description="用户 ID")
    question: str = Field(..., description="用户问题")
    chat_id: Optional[str] = Field(None, description="会话 ID，不传则自动创建新会话")


# ========== 流式生成器 ==========


async def stream_with_save(question: str, chat_id: str, user_id: str):
    """
    流式调用 LLM，逐 token 输出，完成后保存 assistant 消息。

    Args:
        question: 用户问题
        chat_id: 会话 ID
        user_id: 用户 ID

    Yields:
        SSE 格式的事件字符串
    """
    from langchain_core.messages import HumanMessage

    llm = get_llm()
    repo = get_chat_repo()
    full_response = ""

    try:
        async for chunk in llm.astream([HumanMessage(content=question)]):
            if chunk.content:
                full_response += chunk.content
                yield format_sse_event("token", {"content": chunk.content})

        # 流式完成，保存 assistant 消息
        assistant_msg = repo.save_message(
            chat_id=chat_id,
            role="assistant",
            content=full_response,
        )
        if assistant_msg:
            logger.debug(f"assistant 消息已保存: id={assistant_msg['id']}")
        else:
            logger.warning("assistant 消息保存失败")

        yield format_sse_event("done", {"chat_id": chat_id})

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        yield format_sse_event("error", {"message": str(e)})


# ========== API 端点 ==========


@router.post("")
async def create_message(req: MessageRequest):
    """
    发送消息并获取流式回答

    流程：
    1. 如果没有 chat_id，自动创建新会话
    2. 保存用户消息到数据库
    3. 调用 LLM 流式生成回答
    4. 保存 assistant 消息到数据库

    事件类型：
    - token: LLM 生成的 token
    - done: 生成结束，包含 chat_id
    - error: 错误
    """
    repo = get_chat_repo()

    # 1. 确定会话：没有 chat_id 就创建新会话
    chat_id = req.chat_id
    if not chat_id:
        # 用问题的前 20 个字符作为会话标题
        title = req.question[:20] + ("..." if len(req.question) > 20 else "")
        chat = repo.create_chat(user_id=req.user_id, title=title)
        if not chat:
            return create_sse_stream_response(
                generator=_error_stream("创建会话失败"),
                session_id="error",
            )
        chat_id = chat["id"]
        logger.info(f"自动创建新会话: chat_id={chat_id}")

    # 2. 保存用户消息
    user_msg = repo.save_message(
        chat_id=chat_id,
        role="user",
        content=req.question,
        user_id=req.user_id,
    )
    if not user_msg:
        logger.warning("用户消息保存失败，但继续处理")

    # 3. 更新会话的 updated_at 时间戳（触发排序刷新）
    repo.client.table("chats").update(
        {"updated_at": datetime.utcnow().isoformat() + "Z"}
    ).eq("id", chat_id).execute()

    # 4. 流式返回 LLM 回答
    return create_sse_stream_response(
        generator=stream_with_save(req.question, chat_id, req.user_id),
        session_id=chat_id,
    )


async def _error_stream(message: str):
    """错误时的流式响应"""
    yield format_sse_event("error", {"message": message})
