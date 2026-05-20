"""
流式对话 API

提供 SSE 流式响应的对话端点。
"""
import asyncio
import json
import logging
import uuid
from typing import Optional, AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# TODO api/chat 是不是代替了 ask?
router = APIRouter(prefix="/chat", tags=["chat"])
# @router.post("/ask", response_model=AskResponse)
# 这两种语法的区别是什么？
# 如果这个页面定义的是一个路由，那么它的确需要放在 api/ 这个文件夹下面，但是如果它定义的是路由，下面这么多与路由无关的函数就应该放在别的文件夹内
# 另外为什么需要生成流式对话模拟器？我们直接采用流式对话不行吗？还是说无论怎么样都必须要有个模拟器保底？

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


# ========== SSE 事件格式化 ==========


def format_sse_event(event_type: str, data: dict) -> str:
    """
    格式化 SSE 事件

    Args:
        event_type: 事件类型
        data: 事件数据

    Returns:
        SSE 格式的字符串
    """
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


# ========== 流式对话生成器 ==========


async def stream_chat_generator(
    user_id: str,
    session_id: str,
    message: str,
) -> AsyncGenerator[str, None]:
    """
    流式对话生成器

    Yields:
        SSE 格式的事件字符串
    """
    from server.graphs.lyra.graph import run_lyra

    try:
        # 发送开始事件
        yield format_sse_event("start", {"session_id": session_id})

        # 运行莱拉图
        result = await run_lyra(
            user_id=user_id,
            session_id=session_id,
            user_input=message,
        )

        # 发送响应事件
        response = result.get("response", "")
        if response:
            # 模拟流式输出（按句子分割）
            sentences = _split_into_sentences(response)
            for sentence in sentences:
                yield format_sse_event("response", {"content": sentence})
                await asyncio.sleep(0.05)  # 模拟打字效果

        # 发送数据状态事件
        data_status = result.get("data_status")
        if data_status:
            yield format_sse_event("data_status", data_status)

        # 发送结束事件
        yield format_sse_event("end", {
            "should_end": result.get("should_end", False),
            "waiting_for_input": result.get("_waiting_for_input", False),
        })

    except Exception as e:
        logger.error(f"流式对话失败: {e}")
        yield format_sse_event("error", {"message": str(e)})


def _split_into_sentences(text: str) -> list[str]:
    """
    将文本分割成句子（用于模拟流式输出）

    Args:
        text: 完整文本

    Returns:
        句子列表
    """
    import re
    # 按句号、问号、感叹号分割，保留标点
    sentences = re.split(r'([。！？\n])', text)
    # 合并标点
    result = []
    for i in range(0, len(sentences) - 1, 2):
        if sentences[i].strip():
            result.append(sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else ""))
    if len(sentences) % 2 == 1 and sentences[-1].strip():
        result.append(sentences[-1])
    return result if result else [text]


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
    - response: 响应片段
    - data_status: 数据收集状态更新
    - end: 会话结束
    - error: 错误
    """
    session_id = req.session_id or str(uuid.uuid4())

    return StreamingResponse(
        stream_chat_generator(
            user_id=req.user_id,
            session_id=session_id,
            message=req.message,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id,
        },
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
