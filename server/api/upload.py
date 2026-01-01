from fastapi import APIRouter, HTTPException
from server.models.schemas import UploadRequest, UploadResponse
from server.services.document_service import DocumentService
from server.config.settings import SETTINGS
import logging

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload(req: UploadRequest):
    logger.debug(f"收到上传请求，URL: {req.url}, 来源: {req.source}")
    svc = DocumentService()
    
    try:
        logger.debug("开始处理文档摄取")
        doc_id = svc.ingest_document(req.url, source=req.source)
        logger.debug(f"文档摄取完成，文档ID: {doc_id}")
    except Exception as e:
        logger.error(f"处理文档摄取时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
    response = UploadResponse(success=True, doc_id=doc_id)
    logger.debug(f"返回响应: {response}")
    return response