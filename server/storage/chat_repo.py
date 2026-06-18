"""
聊天会话与消息的数据库操作

封装 chats 和 messages 两张表的 CRUD。
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from server.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class ChatRepo:
    """聊天会话与消息的数据库操作"""

    CHATS_TABLE = "chats"
    MESSAGES_TABLE = "messages"

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase()
        return self._client

    # ========== 会话 (chats) ==========

    def create_chat(self, user_id: str, title: Optional[str] = None) -> Optional[Dict]:
        """
        创建一个新的聊天会话

        Args:
            user_id: 用户 ID
            title: 会话标题（可选，默认用第一条消息生成）

        Returns:
            创建的会话数据，失败返回 None
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return None

        try:
            now = datetime.utcnow().isoformat() + "Z"
            data = {
                "user_id": user_id,
                "title": title or "新对话",
                "created_at": now,
                "updated_at": now,
            }
            result = self.client.table(self.CHATS_TABLE).insert(data).execute()

            if result.data and len(result.data) > 0:
                chat = result.data[0]
                logger.info(f"会话创建成功: chat_id={chat['id']}")
                return chat
            return None

        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            return None

    def get_chat(self, chat_id: str) -> Optional[Dict]:
        """获取单个会话"""
        if not self.client:
            return None

        try:
            result = (
                self.client.table(self.CHATS_TABLE)
                .select("*")
                .eq("id", chat_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None

        except Exception as e:
            logger.error(f"获取会话失败: {e}")
            return None

    def list_chats(self, user_id: str, limit: int = 50) -> List[Dict]:
        """
        获取用户的会话列表，按更新时间倒序

        Args:
            user_id: 用户 ID
            limit: 返回数量上限

        Returns:
            会话列表
        """
        if not self.client:
            return []

        try:
            result = (
                self.client.table(self.CHATS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []

        except Exception as e:
            logger.error(f"获取会话列表失败: {e}")
            return []

    def update_chat_title(self, chat_id: str, title: str) -> bool:
        """更新会话标题"""
        if not self.client:
            return False

        try:
            self.client.table(self.CHATS_TABLE).update(
                {"title": title, "updated_at": datetime.utcnow().isoformat() + "Z"}
            ).eq("id", chat_id).execute()
            return True

        except Exception as e:
            logger.error(f"更新会话标题失败: {e}")
            return False

    def delete_chat(self, chat_id: str) -> bool:
        """
        删除会话及其所有消息（先删消息再删会话）
        """
        if not self.client:
            return False

        try:
            # 先删除关联的消息
            self.client.table(self.MESSAGES_TABLE).delete().eq("chat_id", chat_id).execute()
            # 再删除会话
            self.client.table(self.CHATS_TABLE).delete().eq("id", chat_id).execute()
            logger.info(f"会话已删除: chat_id={chat_id}")
            return True

        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False

    # ========== 消息 (messages) ==========

    def save_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        保存一条消息

        Args:
            chat_id: 会话 ID
            role: 角色 ("user" 或 "assistant")
            content: 消息内容
            user_id: 用户 ID（可选）
            metadata: 额外元数据（可选）

        Returns:
            创建的消息数据，失败返回 None
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return None

        try:
            data = {
                "chat_id": chat_id,
                "role": role,
                "content": content,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            if user_id:
                data["user_id"] = user_id
            if metadata:
                data["metadata"] = metadata

            result = self.client.table(self.MESSAGES_TABLE).insert(data).execute()

            if result.data and len(result.data) > 0:
                msg = result.data[0]
                logger.debug(f"消息已保存: id={msg['id']}, role={role}")
                return msg
            return None

        except Exception as e:
            logger.error(f"保存消息失败: {e}")
            return None

    def get_messages(self, chat_id: str, limit: int = 100) -> List[Dict]:
        """
        获取会话的消息列表，按时间正序

        Args:
            chat_id: 会话 ID
            limit: 返回数量上限

        Returns:
            消息列表
        """
        if not self.client:
            return []

        try:
            result = (
                self.client.table(self.MESSAGES_TABLE)
                .select("*")
                .eq("chat_id", chat_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return result.data or []

        except Exception as e:
            logger.error(f"获取消息列表失败: {e}")
            return []


# 全局单例
_chat_repo: Optional[ChatRepo] = None


def get_chat_repo() -> ChatRepo:
    """获取 ChatRepo 单例"""
    global _chat_repo
    if _chat_repo is None:
        _chat_repo = ChatRepo()
    return _chat_repo
