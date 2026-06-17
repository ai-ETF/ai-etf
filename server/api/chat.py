"""
流式对话 API

提供 SSE 流式响应的对话端点，使用 LangGraph 真正的 token 级流式输出。
"""
import logging
import uuid
from typing import Optional, AsyncGenerator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.utils.sse import format_sse_event, create_sse_stream_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ========== 请求/响应模型 ==========

class ChatRequest(BaseModel):
    """对话请求"""
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID（可选，不传则创建新会话）")
    message: str = Field(..., description="用户消息")


class ChatResponse(BaseModel):
    """对话响应"""
    session_id: str = Field(..., description="会话 ID")
    reply: str = Field(..., description="莱拉的回复")
    data_status: Optional[dict] = Field(None, description="数据收集状态")
    should_end: bool = Field(False, description="是否结束对话")
    waiting_for_input: bool = Field(False, description="是否等待用户输入（追问链中断）")


class DataStatusResponse(BaseModel):
    """数据状态响应"""
    session_id: str
    brief_ready: bool
    detail_ready: bool
    progress: str


# ========== 流式对话生成器 ==========


async def stream_chat_generator(
    user_id: str,
    session_id: str,
    message: str,
) -> AsyncGenerator[str, None]:
    """
    真正的流式对话生成器，逐 token 输出 LLM 响应。

    Yields:
        SSE 格式的事件字符串
    """
    from server.graphs.lyra.graph import stream_lyra

    try:
        yield format_sse_event("start", {"session_id": session_id})

        async for event_type, data in stream_lyra(
            user_id=user_id,
            session_id=session_id,
            user_input=message,
        ):
            if event_type == "token":
                # 逐 token 输出 LLM 生成内容
                yield format_sse_event("response", {"content": data["content"]})
            elif event_type == "state_update":
                # 中断/等待状态更新
                if data.get("data_status"):
                    yield format_sse_event("data_status", data["data_status"])

        # 发送结束事件
        yield format_sse_event("end", {
            "should_end": data.get("should_end", False) if event_type == "state_update" else False,
            "waiting_for_input": data.get("_waiting_for_input", False) if event_type == "state_update" else False,
        })

    except Exception as e:
        logger.error(f"流式对话失败: {e}")
        yield format_sse_event("error", {"message": str(e)})


# ========== API 端点 ==========


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """
    同步对话端点

    适用场景：简单交互、不支持 SSE 的客户端。
    """
    from server.graphs.lyra.graph import run_lyra

    session_id = req.session_id or str(uuid.uuid4())

    try:
        result = await run_lyra(
            user_id=req.user_id,
            session_id=session_id,
            user_input=req.message,
        )

        return ChatResponse(
            session_id=session_id,
            reply=result.get("response", ""),
            data_status=result.get("data_status"),
            should_end=result.get("should_end", False),
            waiting_for_input=result.get("_waiting_for_input", False),
        )

    except Exception as e:
        logger.error(f"对话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def chat_stream(req: ChatRequest):
    """
    SSE 流式对话端点

    返回 Server-Sent Events 流，事件类型包括：
    - start: 会话开始
    - response: 逐 token 的响应片段
    - data_status: 数据收集状态更新
    - end: 会话结束
    - error: 错误
    """
    session_id = req.session_id or str(uuid.uuid4())

    return create_sse_stream_response(
        generator=stream_chat_generator(
            user_id=req.user_id,
            session_id=session_id,
            message=req.message,
        ),
        session_id=session_id,
    )


@router.get("/{session_id}/data-status", response_model=DataStatusResponse)
async def get_data_status(session_id: str):
    """
    获取数据收集状态

    用于客户端轮询数据收集进度。
    """
    from server.storage.session_repo import get_session_repo

    try:
        repo = get_session_repo()
        state = await repo.load_state(session_id)

        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        data_status = state.get("data_status", {})

        return DataStatusResponse(
            session_id=session_id,
            brief_ready=data_status.get("brief_ready", False),
            detail_ready=data_status.get("detail_ready", False),
            progress=data_status.get("progress", "0%"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取数据状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/history")
async def get_chat_history(session_id: str):
    """
    获取对话历史

    返回指定会话的完整对话历史。
    """
    from server.storage.session_repo import get_session_repo

    try:
        repo = get_session_repo()
        state = await repo.load_state(session_id)

        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        messages = state.get("messages", [])

        # 转换消息格式
        history = []
        for msg in messages:
            msg_type = type(msg).__name__
            history.append({
                "role": "user" if msg_type == "HumanMessage" else "assistant",
                "content": msg.content if hasattr(msg, "content") else str(msg),
                "timestamp": None,  # LangChain 消息没有时间戳
            })

        return {
            "session_id": session_id,
            "history": history,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取对话历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话

    清除指定会话的所有状态和历史。
    """
    from server.storage.session_repo import get_session_repo

    try:
        repo = get_session_repo()
        success = await repo.delete_session(session_id)

        if not success:
            raise HTTPException(status_code=404, detail="Session not found")

        return {"status": "deleted", "session_id": session_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
