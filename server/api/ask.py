from fastapi import APIRouter, HTTPException
from server.models.schemas import AskRequest, AskResponse
from server.services.qa_service import QAService

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    svc = QAService()
    try:
        result = svc.handle_question(req.question, doc_id=req.doc_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return AskResponse(prompt=result["prompt"], decision=result.get("decision"), top_chunks=result.get("top_chunks"))
