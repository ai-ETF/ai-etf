"""sse 工具单元测试：SSE 事件格式化与流式响应构建。

模块名称：server/utils/sse.py
所测功能：format_sse_event（SSE 事件格式、中文不转义）、
         create_sse_stream_response（media type 与响应头 X-Session-ID 等）
测试方法：纯函数直测，无外部依赖，全程不联网、不连 Supabase。
"""
from server.utils.sse import create_sse_stream_response, format_sse_event


# ==================== format_sse_event ====================


def test_格式正确_data前缀与双换行():
    msg = format_sse_event("message", {"content": "hi"})
    assert msg == 'data: {"type": "message", "content": "hi"}\n\n'


def test_中文不转义_原样输出():
    msg = format_sse_event("message", {"content": "你好"})
    assert "你好" in msg
    assert "\\u4f60" not in msg  # 不出现 \uXXXX 转义


def test_事件类型写入data中():
    msg = format_sse_event("done", {})
    assert '"type": "done"' in msg


# ==================== create_sse_stream_response ====================


async def _empty_stream():
    # 空的异步生成器，仅用于构建 StreamingResponse，内容不被消费
    if False:
        yield


def test_media_type与响应头():
    resp = create_sse_stream_response(_empty_stream(), "sess-123")
    assert resp.media_type == "text/event-stream"
    assert resp.headers["X-Session-ID"] == "sess-123"
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["Connection"] == "keep-alive"
