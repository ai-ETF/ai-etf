from fastapi import APIRouter, HTTPException
from server.models.schemas import AskRequest, AskResponse
from server.services.qa_service import QAService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    logger.debug(f"收到问答请求，问题: {req.question}, 文档ID: {req.doc_id}")
    svc = QAService()
    
    try:
        logger.debug("开始处理问答请求")
        result = svc.handle_question(req.question, doc_id=req.doc_id)
        logger.debug("问答处理完成")
    except Exception as e:
        logger.error(f"处理问答请求时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
    response = AskResponse(
        prompt=result["prompt"], 
        decision=result.get("decision"), 
        top_chunks=result.get("top_chunks")
    )
    logger.debug(f"返回响应")
    return response