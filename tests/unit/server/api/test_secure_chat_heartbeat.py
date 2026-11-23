"""SSE 心跳（with_heartbeat）单元测试。

模块名称：server/api/secure_chat.py
所测功能：with_heartbeat —— 静默期插入 `: ping` 注释帧、数据原样透传、
         源异常向上抛、消费者提前结束时取消后台生产任务。
测试方法：进程内构造异步生成器直测，不联网、不调模型。
"""
import asyncio

import pytest

from server.api.secure_chat import with_heartbeat


async def _collect(agen):
    return [item async for item in agen]


@pytest.mark.asyncio
async def test_数据原样透传_顺序不变_无额外心跳():
    async def source():
        for i in range(3):
            yield f"data: {i}\n\n"

    out = await _collect(with_heartbeat(source(), interval=10))
    assert out == ["data: 0\n\n", "data: 1\n\n", "data: 2\n\n"]


@pytest.mark.asyncio
async def test_静默超过间隔_插入ping注释帧():
    async def source():
        yield "data: 1\n\n"
        await asyncio.sleep(0.06)  # 远大于 interval，必然触发心跳
        yield "data: 2\n\n"

    out = await _collect(with_heartbeat(source(), interval=0.01))
    pings = [item for item in out if item == ": ping\n\n"]
    assert pings, "静默期应插入心跳帧"
    # 心跳不能打乱真实事件顺序
    assert [item for item in out if item != ": ping\n\n"] == ["data: 1\n\n", "data: 2\n\n"]


@pytest.mark.asyncio
async def test_心跳帧是SSE注释_前端会忽略():
    # 冒号开头是 SSE 规范规定的注释行，前端 parseSSELine 只处理 data:/{/[，必须跳过
    assert ": ping\n\n".startswith(":")
    assert not ": ping\n\n".lstrip().startswith(("data:", "{", "["))


@pytest.mark.asyncio
async def test_源异常向上抛出_不被心跳吞掉():
    async def source():
        yield "data: 1\n\n"
        raise ValueError("上游炸了")

    with pytest.raises(ValueError, match="上游炸了"):
        await _collect(with_heartbeat(source(), interval=10))


@pytest.mark.asyncio
async def test_消费者提前结束_取消后台任务():
    cancelled = {"flag": False}

    async def source():
        try:
            yield "data: 1\n\n"
            await asyncio.sleep(30)  # 消费者提前关闭时应被取消
            yield "data: 2\n\n"
        finally:
            cancelled["flag"] = True

    agen = with_heartbeat(source(), interval=10)
    assert await agen.__anext__() == "data: 1\n\n"
    await agen.aclose()

    # 给取消信号一点时间传播
    for _ in range(20):
        if cancelled["flag"]:
            break
        await asyncio.sleep(0.01)
    assert cancelled["flag"], "关闭心跳生成器后应取消底层模型流，避免继续消耗额度"
