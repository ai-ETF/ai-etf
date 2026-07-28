"""
SSE（Server-Sent Events）工具函数
"""
import json
from fastapi.responses import StreamingResponse


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


def create_sse_stream_response(generator, session_id: str) -> StreamingResponse:
    """
    构建标准的 SSE StreamingResponse

    Args:
        generator: 异步生成器，yield SSE 格式字符串
        session_id: 会话 ID，写入响应头

    Returns:
        StreamingResponse 实例
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": session_id,
        },
    )
