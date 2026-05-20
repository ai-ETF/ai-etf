"""
会话状态持久化

将 LangGraph 的会话状态持久化到 Supabase，支持中断后恢复。
"""
from typing import Optional, Dict, Any
from datetime import datetime
import json
import logging

from server.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class SessionRepo:
    """会话状态持久化管理"""

    TABLE_NAME = "conversation_sessions"

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """延迟获取 Supabase 客户端"""
        if self._client is None:
            self._client = get_supabase()
        return self._client

    async def save_state(
        self,
        session_id: str,
        user_id: str,
        state: Dict[str, Any]
    ) -> bool:
        """
        保存或更新会话状态

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            state: 会话状态（LangGraph state dict）

        Returns:
            是否保存成功
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return False

        try:
            # 将 state 中不可序列化的对象转换为可序列化格式
            serializable_state = self._serialize_state(state)

            data = {
                "id": session_id,
                "user_id": user_id,
                "state": serializable_state,
                "updated_at": datetime.utcnow().isoformat()
            }

            result = self.client.table(self.TABLE_NAME).upsert(data).execute()

            if result.data:
                logger.debug(f"会话状态已保存: session_id={session_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"保存会话状态失败: {e}")
            return False

    async def load_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        加载会话状态

        Args:
            session_id: 会话 ID

        Returns:
            会话状态字典，不存在则返回 None
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return None

        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("state")
                .eq("id", session_id)
                .execute()
            )

            if result.data and len(result.data) > 0:
                state = result.data[0].get("state")
                logger.debug(f"会话状态已加载: session_id={session_id}")
                return self._deserialize_state(state)
            return None

        except Exception as e:
            logger.error(f"加载会话状态失败: {e}")
            return None

    async def get_latest_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取用户最近的会话

        Args:
            user_id: 用户 ID

        Returns:
            最近的会话信息，包含 id, user_id, state, updated_at
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return None

        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("user_id", user_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )

            if result.data and len(result.data) > 0:
                session = result.data[0]
                session["state"] = self._deserialize_state(session.get("state", {}))
                return session
            return None

        except Exception as e:
            logger.error(f"获取最近会话失败: {e}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否删除成功
        """
        if not self.client:
            logger.error("Supabase 客户端不可用")
            return False

        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .delete()
                .eq("id", session_id)
                .execute()
            )
            logger.debug(f"会话已删除: session_id={session_id}")
            return True

        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            return False

    def _serialize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        将状态序列化为可存储的 JSON 格式

        处理 LangChain Message 对象等不可直接 JSON 序列化的类型
        """
        serializable = {}

        for key, value in state.items():
            if value is None:
                serializable[key] = None
            elif isinstance(value, (str, int, float, bool, list, dict)):
                serializable[key] = value
            elif hasattr(value, "model_dump"):
                # Pydantic 模型
                serializable[key] = value.model_dump()
            elif hasattr(value, "to_dict"):
                serializable[key] = value.to_dict()
            elif hasattr(value, "__dict__"):
                serializable[key] = str(value)
            else:
                serializable[key] = str(value)

        return serializable

    def _deserialize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        反序列化状态

        目前直接返回，后续可根据需要重建 Message 对象等
        """
        return state if state else {}


# 全局单例
_session_repo: Optional[SessionRepo] = None


def get_session_repo() -> SessionRepo:
    """获取 SessionRepo 单例"""
    global _session_repo
    if _session_repo is None:
        _session_repo = SessionRepo()
    return _session_repo
