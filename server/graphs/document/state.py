"""
文档分析图状态定义
"""
from typing import TypedDict, Optional, Dict, Any, List


class DocumentState(TypedDict, total=False):
    """
    文档分析状态

    输入：content, doc_id
    输出：document_type, key_info_locations, content_structure, suggested_chunk_strategy, confidence
    """
    # 输入
    content: str
    doc_id: Optional[str]

    # 文档类型分类输出
    document_type: str       # financial_report, etf_report, news_article, regulatory_document, general_document
    confidence: float        # 分类置信度 (0-1)

    # 结构分析输出
    key_info_locations: List[Dict[str, Any]]
    content_structure: Dict[str, Any]
    suggested_chunk_strategy: str


def create_document_state(content: str, doc_id: str = None) -> DocumentState:
    """创建文档分析初始状态"""
    return DocumentState(
        content=content,
        doc_id=doc_id,
        document_type="general_document",
        confidence=0.5,
        key_info_locations=[],
        content_structure={},
        suggested_chunk_strategy="按自然段落分块",
    )
