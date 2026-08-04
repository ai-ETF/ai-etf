"""
API 路由聚合器

将各子模块的路由聚合为一个统一的 router，供 app.py 注册。
每个子路由已自带 prefix，此处不再重复添加。

新增模块只需在 __init__.py 中添加 import + include_router，app.py 无需改动。
"""
import logging

"""
API 路由聚合器

将各子模块的路由聚合为一个统一的 router，供 app.py 注册。
每个子路由已自带 prefix，此处不再重复添加。

新增模块只需在 __init__.py 中添加 import + include_router，app.py 无需改动。
"""
import logging

from fastapi import APIRouter

from . import upload, test, secure_chat, watchlist
from .market import router as market_router
from .risk import router as risk_router

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(upload.router)
router.include_router(test.router)
router.include_router(secure_chat.router)
router.include_router(watchlist.router)
router.include_router(market_router)
router.include_router(risk_router)

# 已弃用的 ask 路由不再注册（保留 import 避免破坏旧引用）
# from . import ask
# router.include_router(ask.router)

__all__ = [
    "upload", "test", "secure_chat", "watchlist",
    "market_router", "risk_router", "router",
]