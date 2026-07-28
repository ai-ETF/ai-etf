"""
JWT 验证工具

对接 Supabase Auth：验证 Supabase 签发的 JWT access_token，
从 payload 中提取用户身份信息。
"""
import logging
from typing import Optional

import jwt

from server.config.settings import SETTINGS

logger = logging.getLogger(__name__)


def verify_supabase_token(token: str) -> Optional[dict]:
    """
    验证 Supabase JWT，返回 payload。

    Supabase 签发的 JWT 使用 HS256 算法，密钥为项目设置中的 JWT Secret。
    payload 中的关键字段：
    - sub: 用户 UUID（Supabase auth.users 表的主键）
    - exp: 过期时间
    - role: 用户角色（通常为 "authenticated"）

    Args:
        token: JWT 字符串（不含 "Bearer " 前缀）

    Returns:
        验证成功返回 payload dict，失败返回 None
    """
    secret = SETTINGS.SUPABASE_JWT_SECRET
    if not secret:
        logger.error("未配置 SUPABASE_JWT_SECRET，无法验证 JWT")
        return None

    # 调试日志：显示 secret 的前 10 个字符（隐藏完整密钥）
    logger.debug(f"使用 JWT Secret 验证，密钥前缀: {secret[:10]}...")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_exp": True},  # 验证过期时间
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWT 验证失败: {e}")
        logger.debug(f"Secret 长度: {len(secret)} 字符")
        return None
