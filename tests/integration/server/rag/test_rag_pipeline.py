"""P2-9 RAG 端到端集成测试：QAService.handle_question 完整链路（嵌入→检索→提示词）。

模块名称：问答 RAG 管线
所测功能：真实本地嵌入 → pgvector 检索 → 提示词组装（reranker mock 高分走正常路径）
使用的测试方法：本地 Supabase 栈 + 本地 text2vec 模型 + 真实 auth 用户 + 种入文档 + mock reranker
"""
import uuid

import pytest

pytestmark = pytest.mark.integration


def _create_doc_with_chunks(supabase_client, auth_user_id, embedder, chunks_text):
    file_rec = supabase_client.table("files").insert(
        {"user_id": auth_user_id, "name": f"rag-{uuid.uuid4().hex[:8]}.pdf", "type": "file"}
    ).execute().data[0]
    doc_rec = supabase_client.table("documents").insert(
        {"file_id": file_rec["id"], "user_id": auth_user_id, "status": "ready", "title": "红利ETF说明"}
    ).execute().data[0]
    for i, text in enumerate(chunks_text):
        supabase_client.table("document_chunks").insert(
            {
                "document_id": doc_rec["id"],
                "chunk_index": i,
                "content": text,
                "embedding": embedder.embed_text(text),
                "document_type": "etf_document_chunk",
            }
        ).execute()
    return doc_rec["id"]


@pytest.fixture
def qa_service(supabase_client, monkeypatch):
    """QAService 实例：本地嵌入 + 本地库 + mock reranker（高分，不拒识）。"""
    import os

    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from server.storage import supabase_client as sc

    monkeypatch.setattr(sc, "get_supabase", lambda: supabase_client)

    from server.services.qa_service import QAService

    svc = QAService()

    class FakeReranker:
        model = type("Model", (), {"name_or_path": "fake-reranker"})

        def predict(self, pairs):
            return [0.9] * len(pairs)

    svc.reranker = FakeReranker()
    return svc


def test_handle_question_general意图_RAG检索返回含内容提示词(qa_service, supabase_client, auth_user_id):
    from server.rag.embedder import Embedder

    embedder = Embedder(dim=768)
    _create_doc_with_chunks(
        supabase_client, auth_user_id, embedder,
        [
            "红利ETF跟踪中证红利低波动指数，聚焦高股息率的上市公司股票，适合追求稳定现金流的长期投资者",
            "债券基金主要投资于国债、金融债和企业债，风险较低",
        ],
    )

    result = qa_service.handle_question("红利ETF适合什么样的投资者")

    assert "prompt" in result
    assert result["top_chunks"], "应检索到相关文档内容"
    # 提示词中应包含检索到的「红利」相关内容
    assert "红利" in result["prompt"]
