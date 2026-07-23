"""
API 路由聚合器

将各子模块的路由聚合为一个统一的 router，供 app.py 注册。
每个子路由已自带 prefix，此处不再重复添加。

最终路径结构：
- /api/upload      → upload.py 的 POST ""
- /api/test/hello  → test.py 的 GET "/hello"
- /api/ask         → ask.py 的 POST "" (已弃用)
- /api/simple-chat → simple_chat.py
- /api/messages    → messages.py
- /api/chats       → chat_sessions.py
- /api/secure-chat → secure_chat.py
"""
from fastapi import APIRouter

from . import upload, test, ask, simple_chat, messages, chat_sessions, secure_chat

router = APIRouter()
router.include_router(upload.router)
router.include_router(test.router)
router.include_router(ask.router)
router.include_router(simple_chat.router)
router.include_router(messages.router)
router.include_router(chat_sessions.router)
router.include_router(secure_chat.router)

__all__ = ["upload", "test", "ask", "simple_chat", "messages", "chat_sessions", "secure_chat", "router"]