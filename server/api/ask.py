# [已弃用] 请使用 POST /api/chat 或 POST /api/chat/stream 代替。
# 此接口将在未来版本中移除。

# 导入 FastAPI 路由器和异常类
from fastapi import APIRouter, HTTPException
# 导入请求/响应的数据模型（Pydantic），用于参数校验和序列化
from server.models.schemas import AskRequest, AskResponse
# 导入问答业务逻辑服务层
from server.services.qa_service import QAService
# 导入日志模块
import logging

# 获取当前模块的 logger，日志会带上模块名前缀方便定位
logger = logging.getLogger(__name__)

# 创建 API 路由器
router = APIRouter(prefix="/ask", tags=["ask"])


# POST 接口 [已弃用，请使用 /api/chat]
@router.post("", response_model=AskResponse, deprecated=True)
async def ask(req: AskRequest):
    """
    [已弃用] 请使用 POST /api/chat 或 /api/chat/stream 代替。
    """
    # 记录收到的用户问题和文档 ID（doc_id 为 null 表示不限文档）
    logger.debug(f"收到问答请求，问题: {req.question}, 文档ID: {req.doc_id}")
    # 实例化 QAService，封装检索 + LLM 回答的完整流程
    svc = QAService()

    try:
        logger.debug("开始处理问答请求")
        # 调用业务层处理问题：检索相关片段 → 构造 prompt → 调用 LLM 生成回答
        # 返回 result 字典，包含 prompt、decision（LLM 回答）、top_chunks（命中的文档片段）
        result = svc.handle_question(req.question, doc_id=req.doc_id)
        logger.debug("问答处理完成")
    except Exception as e:
        # 捕获所有异常，记录错误日志并返回 HTTP 500
        logger.error(f"处理问答请求时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # 将业务层返回的字典组装成 AskResponse 模型
    response = AskResponse(
        prompt=result["prompt"],              # 发送给 LLM 的完整提示词（含检索到的上下文）
        decision=result.get("decision"),      # LLM 生成的回答文本
        top_chunks=result.get("top_chunks")   # 检索命中的文档片段列表，用于前端展示来源
    )
    logger.debug(f"返回响应")
    return response