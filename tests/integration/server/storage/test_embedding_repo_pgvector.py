"""P0-1 存储层集成测试：EmbeddingRepo/Retriever ↔ 真实 Postgres + pgvector。

模块名称：嵌入向量存储与检索
所测功能：真实嵌入写入 document_chunks、match_chunks 稠密检索、match_chunks_fts 稀疏检索、双路 RRF 融合
使用的测试方法：本地 Supabase 栈 + 本地 text2vec 模型（离线）+ 真实 auth 用户（FK 链）+ 定向清理
"""
import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def embedder():
    """本地 text2vec 嵌入模型（离线，module 级复用）。"""
    import os

    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from server.rag.embedder import Embedder

    return Embedder(dim=768)


@pytest.fixture
def embedding_repo(supabase_client, monkeypatch):
    """EmbeddingRepo 实例，supabase 指向本地库。"""
    from server.storage import supabase_client as sc

    monkeypatch.setattr(sc, "get_supabase", lambda: supabase_client)
    from server.storage.embedding_repo import EmbeddingRepo

    return EmbeddingRepo()


def _create_doc_with_chunks(supabase_client, auth_user_id, embedder, chunks_text):
    """创建 auth用户→files→documents→document_chunks 完整 FK 链，返回 document_id。"""
    file_rec = supabase_client.table("files").insert(
        {"user_id": auth_user_id, "name": f"test-{uuid.uuid4().hex[:8]}.pdf", "type": "file"}
    ).execute().data[0]

    doc_rec = supabase_client.table("documents").insert(
        {"file_id": file_rec["id"], "user_id": auth_user_id, "status": "ready", "title": "测试文档"}
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


def test_match_by_vector_稠密检索命中语义相近chunk(embedding_repo, supabase_client, auth_user_id, embedder):
    doc_id = _create_doc_with_chunks(
        supabase_client, auth_user_id, embedder,
        [
            "红利ETF跟踪中证红利低波动指数，聚焦高股息率的上市公司股票",
            "债券基金主要投资于国债、金融债和企业债，风险较低",
        ],
    )

    query_vec = embedder.embed_text("红利ETF的股息率是多少")
    results = embedding_repo.match_by_vector(query_vec, top_k=2, doc_id=doc_id)

    assert len(results) >= 1
    # 最相似的是「红利」chunk（语义相近）
    assert "红利" in results[0]["content"]
    # similarity 为余弦相似度（1 - 距离），应在 0~1 区间
    assert 0.0 <= float(results[0]["similarity"]) <= 1.0


def test_match_by_keywords_稀疏检索命中关键词(embedding_repo, supabase_client, auth_user_id, embedder):
    # 用英文 content：FTS 用 simple 配置，default parser 对中文完全不切分
    # （「跟踪沪深300指数」是单个 token，数字也不分离），故用英文验证 FTS 检索本身是通的。
    doc_id = _create_doc_with_chunks(
        supabase_client, auth_user_id, embedder,
        [
            "This fund tracks the CSI 300 index, focusing on large-cap blue-chip stocks",
            "This fund invests in money market instruments with high liquidity",
        ],
    )

    results = embedding_repo.match_by_keywords("CSI 300", top_k=5, doc_id=doc_id)

    assert len(results) >= 1
    # 命中含「CSI」关键词的 chunk
    assert any("CSI" in r.get("content", "") for r in results)


def test_retriever_双路融合返回结果(embedding_repo, supabase_client, auth_user_id, embedder):
    doc_id = _create_doc_with_chunks(
        supabase_client, auth_user_id, embedder,
        [
            "红利ETF跟踪中证红利低波动指数，聚焦高股息率的上市公司股票",
            "债券基金主要投资于国债、金融债和企业债，风险较低",
        ],
    )

    from server.rag.retriever import Retriever

    retriever = Retriever(embedding_repo)
    query_vec = embedder.embed_text("红利ETF股息率")
    results = retriever.retrieve(query_vec, top_k=2, doc_id=doc_id, query_text="红利ETF股息率")

    assert len(results) >= 1
    # 融合结果含 chunk_id / content / similarity 字段
    assert "chunk_id" in results[0]
    assert "content" in results[0]
    assert "similarity" in results[0]
