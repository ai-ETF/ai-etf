from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class UploadRequest(BaseModel):
    """
    上传请求的数据模型
    定义了上传文档API的请求体结构
    """
    url: str  # 要上传的文档URL
    source: Optional[str] = None  # 文档来源（可选）


class UploadResponse(BaseModel):
    """
    上传响应的数据模型
    定义了上传文档API的响应体结构
    """
    success: bool  # 上传是否成功
    doc_id: Optional[str]  # 生成的文档ID（如果成功）


class AskRequest(BaseModel):
    """
    问答请求的数据模型
    定义了提问API的请求体结构
    """
    question: str  # 用户的问题
    doc_id: Optional[str] = None  # 限制搜索范围的文档ID（可选）


class Chunk(BaseModel):
    """
    文本块的数据模型
    用于表示检索到的相关文本块
    """
    chunk_id: str  # 文本块ID
    text: str  # 文本内容
    score: float  # 与问题的相似度得分


class AskResponse(BaseModel):
    """
    问答响应的数据模型
    定义了提问API的响应体结构
    """
    prompt: str  # 构建的完整提示词
    decision: Optional[Any]  # 决策结果（意图、输出格式等）
    top_chunks: Optional[List[Chunk]]  # 相关的文本块列表


class ProcessFileFromEdgeRequest(BaseModel):
    """
    Edge Function发送的文件处理请求数据模型
    """
    file_id: str
    user_id: str
    download_url: str
    doc_type: Optional[str] = "general_document"
    parse_strategy: Optional[Dict[str, Any]] = None