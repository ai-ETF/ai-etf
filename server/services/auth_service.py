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

from server.auth.token_store import revoke
from server.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# 密码最小长度（应用层强制，Supabase 端 minimum_password_length 同样为 8）
PASSWORD_MIN_LENGTH = 8

# 轻量邮箱格式校验，避免额外引入 email-validator 依赖
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Supabase Auth 错误码 → (HTTP 状态码, 文案)。
# 关键在于区分三类语义，不能一律 502：
#   - 参数错（400/409）：用户改输入即可
#   - 限流（429）：稍后重试有意义
#   - 配置/权限（403/503）：重试一万次也没用，必须让运维改配置
# 完整错误码见 supabase_auth.errors.ErrorCode。
_AUTH_ERROR_MAP: dict[str, tuple[int, str]] = {
    "user_already_exists": (409, "该邮箱已注册，请直接登录"),
    "email_address_invalid": (400, "邮箱格式不正确"),
    "weak_password": (400, f"密码不符合安全要求，请设置至少 {PASSWORD_MIN_LENGTH} 位"),
    "over_request_rate_limit": (429, "注册请求过于频繁，请稍后重试"),
    "over_email_send_rate_limit": (429, "注册请求过于频繁，请稍后重试"),
    "over_sms_send_rate_limit": (429, "注册请求过于频繁，请稍后重试"),
    "signup_disabled": (403, "当前未开放注册"),
    "email_provider_disabled": (403, "当前未开放注册"),
    # 仅在邮箱确认开启 + SMTP 未配置时出现；本设计为「注册即激活」，走到这里说明配置漂移了
    "email_address_not_authorized": (503, "注册邮件通道未配置，请联系管理员"),
}


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
        HTTPException: 400 参数非法 / 403 未开放注册 / 409 邮箱已注册 /
            429 请求过于频繁 / 500 数据库未就绪 / 502 未知服务异常 / 503 邮件通道未配置
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
        raise HTTPException(status_code=400, detail=_AUTH_ERROR_MAP["weak_password"][1])
    except AuthApiError as e:
        logger.warning(f"注册失败: code={e.code}, status={e.status}, message={e.message}")
        mapped = _AUTH_ERROR_MAP.get(e.code or "")
        if mapped:
            raise HTTPException(status_code=mapped[0], detail=mapped[1])
        # 未覆盖的 Auth 错误按服务不可用处理；原始 code 已在上面日志里，便于复盘
        raise HTTPException(status_code=502, detail="注册服务暂时不可用，请稍后重试")
    except Exception as e:
        logger.error(f"注册发生未知异常: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="注册服务暂时不可用，请稍后重试")

    user_id = getattr(result.user, "id", None)
    if result.session is not None:
        logger.info(f"用户注册成功: user_id={user_id}, auto_login=True")
    else:
        # 本项目设计为「注册即激活」：Supabase 端应关闭 Confirm email，sign_up 直接签发 session。
        # 返回空 session 说明线上配置与设计不符——注册会「成功」但用户拿不到登录态，
        # 前端表现为「点了注册没反应」。必须大声报出来，否则又是一次 502 式的哑巴故障。
        logger.warning(
            f"用户注册成功但未返回 session: user_id={user_id}，"
            "疑似 Supabase 端仍开启邮箱确认（Confirm email），"
            "请在 Authentication → Sign In / Providers → Email 关闭该开关"
        )
    return {"session": result.session, "user": result.user}


# ========== 退出登录 ==========


def logout_user(token: str, exp: float) -> None:
    """
    退出登录。

    - 本地撤销 access token（撤销清单使其即时失效）
    - 调用 Supabase admin.sign_out 撤销该会话的 refresh token（服务端登出）

    Args:
        token: 用户的 access token
        exp: 该 token 的过期时间（epoch 秒）
    """
    revoke(token, exp)

    supabase = get_supabase()
    if not supabase:
        logger.warning("数据库未就绪，跳过 refresh token 撤销（access token 已本地失效）")
        return
    try:
        supabase.auth.admin.sign_out(token, "global")
        logger.info("已撤销 Supabase refresh token")
    except Exception as e:
        # 幂等操作：token 已本地撤销，Supabase 侧失败不阻塞返回
        logger.warning(f"撤销 Supabase refresh token 失败: {e}")


# ========== 注销账号 ==========
# 业务数据清理由数据库函数 public.purge_user_data(uuid) 在单个事务内完成
# （迁移：supabase/migrations/20260829150730_purge_user_data.sql），
# 覆盖 13 张含 user_id 的业务表，子表 document_chunks / message_chunks 由 FK CASCADE 清理。


def delete_account(user_id: str, email: str, password: str) -> None:
    """
    注销账号（不可逆）：复核密码 → RPC 清理业务数据 → 删除 auth 账号。

    密码复核：用邮箱+密码重新登录，成功即证明密码正确；防止被盗用 token 的人随意删号。

    Args:
        user_id: Supabase auth.users 的 UUID（来自 JWT）
        email: 用户邮箱（来自 JWT payload，用于复核密码）
        password: 用户输入的密码

    Raises:
        HTTPException: 401 密码错误 / 500 数据库未就绪 / 502 清理或删除失败
    """
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="数据库连接未就绪")

    # 1) 复核密码
    try:
        supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        logger.warning(f"注销密码复核失败: {e}")
        raise HTTPException(status_code=401, detail="密码错误")

    # 2) 清理业务数据 + 删除账号。
    #    用新客户端执行：sign_in 会让原客户端携带用户 session，
    #    若复用则 RPC 会以 authenticated 身份调用（函数仅授权 service_role，
    #    且 SECURITY DEFINER 函数不能让普通用户任意调用）。
    admin = get_supabase()
    if not admin:
        raise HTTPException(status_code=500, detail="数据库连接未就绪")

    try:
        admin.rpc("purge_user_data", {"p_user_id": user_id}).execute()
        logger.info(f"业务数据已清理: user_id={user_id}")
    except Exception as e:
        logger.error(f"清理业务数据失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=502, detail="注销失败，清理用户数据时出错，请重试"
        )

    try:
        admin.auth.admin.delete_user(user_id)
    except Exception as e:
        # sign_up 注册的用户 admin.delete_user 会报「User not allowed」，
        # 降级用 SQL 直删（delete_auth_user RPC，SECURITY DEFINER）兜底
        logger.warning(f"admin.delete_user 失败（sign_up 用户可能报 User not allowed），降级 SQL 直删: {e}")
        try:
            admin.rpc("delete_auth_user", {"p_user_id": user_id}).execute()
        except Exception as e2:
            logger.error(f"SQL 直删 auth 用户也失败: {e2}", exc_info=True)
            raise HTTPException(status_code=502, detail="注销失败，删除账号时出错，请重试")

    logger.info(f"账号已注销: user_id={user_id}")
