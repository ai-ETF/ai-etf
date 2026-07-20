"""
会话管理 API

提供会话列表、消息历史、删除会话等端点。
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.storage.chat_repo import get_chat_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


# ========== 响应模型 ==========


class ChatInfo(BaseModel):
    """会话信息"""
    id: str
    user_id: str
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageInfo(BaseModel):
    """消息信息"""
    id: str
    chat_id: str
    role: str
    content: str
    created_at: Optional[str] = None


# ========== API 端点 ==========


@router.get("")
async def list_chats(
    user_id: str = Query(..., description="用户 ID"),
    limit: int = Query(50, ge=1, le=200, description="返回数量上限"),
):
    """
    获取用户的会话列表

    按更新时间倒序返回。
    """
    repo = get_chat_repo()
    chats = repo.list_chats(user_id=user_id, limit=limit)

    return {
        "total": len(chats),
        "chats": [
            ChatInfo(
                id=c["id"],
                user_id=c["user_id"],
                title=c.get("title"),
                created_at=c.get("created_at"),
                updated_at=c.get("updated_at"),
            )
            for c in chats
        ],
    }


@router.get("/{chat_id}/messages")
async def get_chat_messages(
    chat_id: str,
    limit: int = Query(100, ge=1, le=500, description="返回数量上限"),
):
    """
    获取某次会话的消息历史

    按时间正序返回。
    """
    repo = get_chat_repo()

    # 先检查会话是否存在
    chat = repo.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = repo.get_messages(chat_id=chat_id, limit=limit)

    return {
        "chat_id": chat_id,
        "chat_title": chat.get("title"),
        "total": len(messages),
        "messages": [
            MessageInfo(
                id=m["id"],
                chat_id=m["chat_id"],
                role=m["role"],
                content=m["content"],
                created_at=m.get("created_at"),
            )
            for m in messages
        ],
    }


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str):
    """
    删除会话及其所有消息
    """
    repo = get_chat_repo()

    # 先检查会话是否存在
    chat = repo.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")

    success = repo.delete_chat(chat_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除会话失败")

    return {"message": "会话已删除", "chat_id": chat_id}
