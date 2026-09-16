"""
带 JWT 认证的 LLM 对话 API

提供登录、发送消息、会话管理等端点，所有接口（除登录外）需要 JWT 认证。
user_id 从 JWT token 中自动读取，不从请求体取，杜绝冒充。
"""
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.auth import get_current_user
from server.auth.deps import extract_and_verify
from server.llm import astream_text, get_llm
from server.services.auth_service import delete_account, logout_user, register_user
from server.storage.chat_repo import get_chat_repo
from server.storage.supabase_client import get_supabase
from server.utils.sse import format_sse_event, create_sse_stream_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/secure-chat", tags=["secure-chat"])


# ========== 请求/响应模型 ==========


class LoginRequest(BaseModel):
    """登录请求"""
    email: str = Field(..., description="邮箱")
    password: str = Field(..., description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    expires_in: int


class RegisterRequest(BaseModel):
    """注册请求"""
    email: str = Field(..., description="邮箱")
    password: str = Field(..., description="密码（至少 8 位）")


class RegisterResponse(BaseModel):
    """注册响应（兼容 auto-confirm 与邮箱确认两种模式）"""
    success: bool
    needs_email_confirmation: bool
    access_token: Optional[str] = None
    token_type: str = "bearer"
    user_id: Optional[str] = None
    expires_in: Optional[int] = None
    message: str


class DeleteAccountRequest(BaseModel):
    """注销账号请求"""
    password: str = Field(..., description="账号密码（用于复核，防止 token 被盗后随意删号）")


class SecureMessageRequest(BaseModel):
    """受保护的消息请求（不需要 user_id，从 JWT 中读取）"""
    question: str = Field(..., description="用户问题")
    chat_id: Optional[str] = Field(None, description="会话 ID，不传则自动创建新会话")


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


# ========== 登录端点（不需要 JWT）==========


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """
    登录接口 —— 调用 Supabase Auth 验证邮箱密码，返回 JWT access_token。

    后续所有请求都需要在 Header 中携带此 token。
    """
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=500, detail="数据库连接未就绪")

    try:
        result = supabase.auth.sign_in_with_password(
            {"email": req.email, "password": req.password}
        )
    except Exception as e:
        logger.warning(f"登录失败: {e}")
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    session = result.session
    user = result.user
    if not session or not user:
        raise HTTPException(status_code=401, detail="登录失败，请检查邮箱和密码")

    logger.info(f"用户登录成功: user_id={user.id}")
    return LoginResponse(
        access_token=session.access_token,
        user_id=user.id,
        expires_in=session.expires_in or 3600,
    )


# ========== 注册端点（不需要 JWT）==========


@router.post("/register", response_model=RegisterResponse)
async def register(req: RegisterRequest):
    """
    注册接口 —— 调用 Supabase Auth 注册新用户。

    - 密码至少 8 位；重复邮箱返回 409。
    - auto-confirm 模式（当前 enable_confirmations=false）：注册即激活，直接返回 JWT 登录态。
    - 邮箱确认模式：不返回 session，提示用户查收邮件后走登录接口。
    """
    result = register_user(email=req.email, password=req.password)
    session = result.get("session")
    user = result.get("user")

    if session:
        # auto-confirm 模式：注册即激活，返回登录态
        return RegisterResponse(
            success=True,
            needs_email_confirmation=False,
            access_token=session.access_token,
            user_id=user.id,
            expires_in=session.expires_in or 3600,
            message="注册成功，已自动登录",
        )

    # 邮箱确认模式：需用户查收邮件确认后再登录
    return RegisterResponse(
        success=True,
        needs_email_confirmation=True,
        message="注册成功，请前往邮箱完成验证后登录",
    )


# ========== 退出登录 / 注销账号（需要 JWT）==========


@router.post("/logout")
async def logout(authorization: str = Header(...)):
    """
    退出登录 —— 撤销当前 access token（本地即时失效）与 Supabase refresh token。

    幂等操作：token 已失效或重复登出均返回成功。
    """
    token, payload = extract_and_verify(authorization)
    exp = payload.get("exp") or time.time() + 3600
    logout_user(token=token, exp=exp)
    return {"success": True, "message": "退出登录成功"}


@router.post("/delete-account")
async def delete_account_endpoint(
    req: DeleteAccountRequest,
    authorization: str = Header(...),
):
    """
    注销账号 —— 不可逆操作：复核密码后，RPC 清理全部业务数据并删除 Supabase 账号。

    需携带 JWT 并提交账号密码。注销成功后当前 token 即失效。
    """
    token, payload = extract_and_verify(authorization)
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id or not email:
        raise HTTPException(status_code=401, detail="令牌中未包含用户信息")

    delete_account(user_id=user_id, email=email, password=req.password)
    # 账号已删除，立即使当前 access token 失效
    exp = payload.get("exp") or time.time() + 3600
    logout_user(token=token, exp=exp)
    return {"success": True, "message": "账号已注销"}


# ========== 流式生成器 ==========


async def stream_with_save(question: str, chat_id: str, user_id: str):
    """
    流式调用 LLM，逐 token 输出，完成后保存 assistant 消息。
    """
    from langchain_core.messages import HumanMessage

    llm = get_llm()
    repo = get_chat_repo()
    full_response = ""

    try:
        async for text in astream_text(llm, [HumanMessage(content=question)]):
            full_response += text
            yield format_sse_event("token", {"content": text})

        # 流式完成，保存 assistant 消息
        assistant_msg = repo.save_message(
            chat_id=chat_id,
            role="assistant",
            content=full_response,
            user_id=user_id,
        )
        if assistant_msg:
            logger.debug(f"assistant 消息已保存: id={assistant_msg['id']}")
        else:
            logger.warning("assistant 消息保存失败")

        yield format_sse_event("done", {"chat_id": chat_id})

    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        yield format_sse_event("error", {"message": str(e)})


async def _error_stream(message: str):
    """错误时的流式响应"""
    yield format_sse_event("error", {"message": message})


# ========== 受保护的消息端点 ==========


@router.post("")
async def create_secure_message(
    req: SecureMessageRequest,
    current_user: str = Depends(get_current_user),
):
    """
    发送消息并获取流式回答（需 JWT 认证）

    user_id 从 JWT token 中自动读取，无需在请求体中传入。

    流程：
    1. 如果没有 chat_id，自动创建新会话
    2. 保存用户消息到数据库
    3. 调用 LLM 流式生成回答
    4. 保存 assistant 消息到数据库
    """
    repo = get_chat_repo()
    user_id = current_user  # 来自 JWT，不是来自请求体

    # 1. 确定会话：没有 chat_id 就创建新会话
    chat_id = req.chat_id
    if not chat_id:
        title = req.question[:20] + ("..." if len(req.question) > 20 else "")
        try:
            chat = repo.create_chat(user_id=user_id, title=title)
        except Exception as e:
            logger.error(f"创建会话异常: {type(e).__name__}: {e}")
            chat = None
        if not chat:
            return create_sse_stream_response(
                generator=_error_stream("创建会话失败，请检查 Supabase 连接和 chats 表是否存在"),
                session_id="error",
            )
        chat_id = chat["id"]
        logger.info(f"自动创建新会话: chat_id={chat_id}, user_id={user_id}")

    # 2. 保存用户消息
    user_msg = repo.save_message(
        chat_id=chat_id,
        role="user",
        content=req.question,
        user_id=user_id,
    )
    if not user_msg:
        logger.warning("用户消息保存失败，但继续处理")

    # 3. 更新会话的 updated_at 时间戳
    repo.client.table("chats").update(
        {"updated_at": datetime.utcnow().isoformat() + "Z"}
    ).eq("id", chat_id).execute()

    # 4. 流式返回 LLM 回答
    return create_sse_stream_response(
        generator=stream_with_save(req.question, chat_id, user_id),
        session_id=chat_id,
    )


# ========== 受保护的会话管理端点 ==========


@router.get("/chats")
async def list_secure_chats(
    limit: int = 50,
    current_user: str = Depends(get_current_user),
):
    """
    获取当前用户的会话列表（需 JWT 认证）

    user_id 从 JWT 中读取，只返回该用户的会话。
    """
    repo = get_chat_repo()
    chats = repo.list_chats(user_id=current_user, limit=limit)

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


@router.get("/chats/{chat_id}/messages")
async def get_secure_chat_messages(
    chat_id: str,
    limit: int = 100,
    current_user: str = Depends(get_current_user),
):
    """
    获取某次会话的消息历史（需 JWT 认证）

    会验证会话是否属于当前用户。
    """
    repo = get_chat_repo()

    # 检查会话是否存在
    chat = repo.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证会话归属：只能看自己的会话
    if chat.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="无权访问此会话")

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


@router.delete("/chats/{chat_id}")
async def delete_secure_chat(
    chat_id: str,
    current_user: str = Depends(get_current_user),
):
    """
    删除会话及其所有消息（需 JWT 认证）

    会验证会话是否属于当前用户。
    """
    repo = get_chat_repo()

    # 检查会话是否存在
    chat = repo.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证会话归属：只能删自己的会话
    if chat.get("user_id") != current_user:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    success = repo.delete_chat(chat_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除会话失败")

    return {"message": "会话已删除", "chat_id": chat_id}
