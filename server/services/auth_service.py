"""
用户认证服务

封装 Supabase Auth 的注册（sign_up），统一异常 → HTTP 错误映射。

登录逻辑保留在 server/api/secure_chat.py 内（现状不变），
此模块仅沉淀注册所需的数据校验与 Supabase 调用。
"""
import logging
import re

from fastapi import HTTPException
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from server.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# 密码最小长度（应用层强制，Supabase 端 minimum_password_length 同样为 8）
PASSWORD_MIN_LENGTH = 8

# 轻量邮箱格式校验，避免额外引入 email-validator 依赖
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(email: str) -> None:
    """校验邮箱格式，非法时抛出 400。"""
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")


def validate_password(password: str) -> None:
    """校验密码长度，不足时抛出 400。"""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=400, detail=f"密码长度至少 {PASSWORD_MIN_LENGTH} 位"
        )


def register_user(email: str, password: str) -> dict:
    """
    注册新用户。

    Args:
        email: 邮箱
        password: 密码（至少 8 位）

    Returns:
        {"session": AuthResponse.session 或 None, "user": AuthResponse.user}

    Raises:
        HTTPException: 400 参数非法 / 409 邮箱已注册 / 500 数据库未就绪 / 502 服务异常
    """
    validate_email(email)
    validate_password(password)

    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="数据库连接未就绪")

    try:
        result = supabase.auth.sign_up({"email": email, "password": password})
    except AuthWeakPasswordError:
        # 兜底：应用层已校验长度，此处防御 Supabase 端密码策略变更
        logger.warning("Supabase 判定密码过弱")
        raise HTTPException(
            status_code=400, detail=f"密码不符合安全要求，请设置至少 {PASSWORD_MIN_LENGTH} 位"
        )
    except AuthApiError as e:
        logger.warning(f"注册失败: code={e.code}, status={e.status}, message={e.message}")
        if e.code == "user_already_exists":
            raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录")
        if e.code == "email_address_invalid":
            raise HTTPException(status_code=400, detail="邮箱格式不正确")
        if e.code == "weak_password":
            raise HTTPException(
                status_code=400, detail=f"密码不符合安全要求，请设置至少 {PASSWORD_MIN_LENGTH} 位"
            )
        # 其余 Auth API 错误（限流、禁用注册等）统一按服务不可用处理
        raise HTTPException(status_code=502, detail="注册服务暂时不可用，请稍后重试")
    except Exception as e:
        logger.error(f"注册发生未知异常: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="注册服务暂时不可用，请稍后重试")

    user_id = getattr(result.user, "id", None)
    has_session = result.session is not None
    logger.info(f"用户注册成功: user_id={user_id}, auto_login={has_session}")
    return {"session": result.session, "user": result.user}
