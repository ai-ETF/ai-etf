from fastapi import APIRouter, HTTPException, Request
from server.models.schemas import UploadRequest, UploadResponse
from server.services.document_service import DocumentService
from server.config.settings import SETTINGS
import logging
import json

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


@router.post("/process-file-from-edge")
async def process_file_from_edge(request: Request):
    """
    专门用于处理来自Edge Function的文件处理请求
    请求体包含: file_id, user_id, download_url, doc_type, parse_strategy
    """
    logger.debug("收到Edge Function文件处理请求")
    
    try:
        # 获取请求体数据
        body = await request.json()
        logger.debug(f"请求体: {body}")
        
        # 验证必需字段
        required_fields = ['file_id', 'user_id', 'download_url']
        for field in required_fields:
            if field not in body:
                raise HTTPException(status_code=400, detail=f"缺少必需字段: {field}")
        
        file_id = body['file_id']
        user_id = body['user_id']
        download_url = body['download_url']
        doc_type = body.get('doc_type', 'general_document')
        parse_strategy = body.get('parse_strategy', {})
        
        logger.debug(f"处理参数 - file_id: {file_id}, user_id: {user_id}, doc_type: {doc_type}")
        
        # 初始化文档服务
        svc = DocumentService()
        
        # 调用处理方法
        logger.debug("开始处理文档...")
        document_id = svc.process_file_from_edge(
            file_id=file_id,
            user_id=user_id,
            download_url=download_url,
            doc_type=doc_type,
            parse_strategy=parse_strategy
        )
        
        logger.debug(f"文档处理完成，document_id: {document_id}")
        
        return {
            "success": True,
            "document_id": document_id
        }
        
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"处理Edge Function请求时发生错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "service": "document-processing"}