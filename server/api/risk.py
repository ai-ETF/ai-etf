"""
风险画像 API 端点

提供风险问卷获取、答案提交、画像查询功能。
user_id 从 JWT 中自动读取。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from server.auth import get_current_user
from server.models.schemas import (
    SubmitRequest,
    QuestionnaireResponse,
    QuestionItem,
    QuestionOption,
    SubmitResponse,
    ProfileResult,
    ProfileResponse,
)
from server.services.risk_service import RiskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/questionnaire", response_model=QuestionnaireResponse)
async def get_questionnaire(
    current_user: str = Depends(get_current_user),
):
    """
    获取当前最新可用的风险问卷。

    返回结构化的题目列表供前端渲染。
    题目中仅包含前端需要的字段（question、options.text/value、category），
    不包含 weight、risk_score 等内部计算字段。
    """
    logger.info(f"获取问卷: user={current_user}")
    svc = RiskService()

    questionnaire = svc.get_active_questionnaire()
    if not questionnaire:
        raise HTTPException(status_code=404, detail="问卷不存在或已停用")

    # 移除内部字段，只返回前端需要的内容
    questions_raw = questionnaire.get("questions", [])
    questions = [
        QuestionItem(
            id=q["id"],
            question=q["question"],
            category=q.get("category", ""),
            options=[
                QuestionOption(text=opt["text"], value=opt["value"])
                for opt in q.get("options", [])
            ],
        )
        for q in questions_raw
    ]

    return QuestionnaireResponse(
        id=questionnaire["id"],
        version=questionnaire.get("version", ""),
        questions=questions,
        total_questions=len(questions),
    )


@router.post("/submit", response_model=SubmitResponse, status_code=201)
async def submit_answers(
    req: SubmitRequest,
    current_user: str = Depends(get_current_user),
):
    """
    提交问卷答案。

    后端校验答案合法性，计算风险画像并存储。
    返回画像结果（等级、得分、维度分析、解读文字）。
    同一用户对同一问卷重复提交会覆盖旧记录。
    """
    logger.info(f"提交问卷: user={current_user}, questionnaire={req.questionnaire_id}")
    svc = RiskService()

    raw_answers = [a.dict() for a in req.answers]
    result = svc.submit_answers(
        user_id=current_user,
        questionnaire_id=req.questionnaire_id,
        answers=raw_answers,
    )

    if not result["success"]:
        # 区分业务错误和系统错误
        raise HTTPException(status_code=400, detail=result["message"])

    return SubmitResponse(
        success=True,
        message=result["message"],
        profile=ProfileResult(**result["profile"]) if result.get("profile") else None,
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: str = Depends(get_current_user),
):
    """
    查询当前用户的画像结果。

    返回最新的活跃画像，包含风险等级、得分、维度分析和解读。
    如果用户尚未填写问卷，返回 has_profile=false。
    """
    logger.info(f"查询画像: user={current_user}")
    svc = RiskService()

    profile = svc.get_latest_profile(user_id=current_user)

    if not profile:
        return ProfileResponse(has_profile=False, profile=None)

    return ProfileResponse(
        has_profile=True,
        profile=ProfileResult(**profile),
    )


@router.get("/health")
async def health_check():
    """健康检查（公开）"""
    return {"status": "ok", "service": "risk"}
