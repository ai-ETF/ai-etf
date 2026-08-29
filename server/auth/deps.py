"""
FastAPI 认证依赖注入

提供 get_current_user 依赖函数，供各 API 路由模块使用。
原定义在 server/api/secure_chat.py 中，提取至此以消除跨模块依赖。
"""
import logging

from fastapi import Depends, Header, HTTPException

from server.auth.jwt_handler import verify_supabase_token
from server.auth.token_store import is_revoked

logger = logging.getLogger(__name__)


def extract_and_verify(authorization: str) -> tuple[str, dict]:
    """
    从 Authorization header 提取并验证 JWT，返回 (token, payload)。

    已登出 / 注销的 token 会被撤销清单拦截，视为无效。

    Raises:
        HTTPException: 401
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="认证格式错误，应为 Bearer <token>")

    token = authorization[7:]  # 去掉 "Bearer " 前缀
    payload = verify_supabase_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    if is_revoked(token):
        raise HTTPException(status_code=401, detail="令牌已注销，请重新登录")

    return token, payload


async def get_current_user(authorization: str = Header(...)) -> str:
    """
    从 Authorization header 中提取并验证 JWT，返回 user_id（Supabase UUID）。

    前端请求格式：Authorization: Bearer eyJhbGci...

    作为 FastAPI Depends 使用：
        async def my_endpoint(..., current_user: str = Depends(get_current_user)):
    """
    _, payload = extract_and_verify(authorization)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="令牌中未包含用户信息")

    return user_id
