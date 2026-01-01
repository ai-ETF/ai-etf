from pydantic import BaseModel
from typing import Optional, List, Any


class UploadRequest(BaseModel):
    url: str
    source: Optional[str] = None


class UploadResponse(BaseModel):
    success: bool
    doc_id: Optional[str]


class AskRequest(BaseModel):
    question: str
    doc_id: Optional[str] = None


class Chunk(BaseModel):
    chunk_id: str
    text: str
    score: float


class AskResponse(BaseModel):
    prompt: str
    decision: Optional[Any]
    top_chunks: Optional[List[Chunk]]
