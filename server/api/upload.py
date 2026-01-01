from fastapi import APIRouter, HTTPException
from server.models.schemas import UploadRequest, UploadResponse
from server.services.document_service import DocumentService
from server.config.settings import SETTINGS

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload(req: UploadRequest):
    svc = DocumentService()
    try:
        doc_id = svc.ingest_document(req.url, source=req.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return UploadResponse(success=True, doc_id=doc_id)
