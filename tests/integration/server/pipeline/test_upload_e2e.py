"""P3 上传端到端集成测试：DocumentService.process_file_from_edge 完整链路。

模块名称：文档上传/处理管线
所测功能：下载（mock）→ 建 documents → 图分析 → 分片嵌入 → 写 document_chunks → 状态 ready
使用的测试方法：真实 DocumentService（本地 text2vec 嵌入）+ mock requests.get + 真实 auth 用户 + 本地库
"""
import asyncio
import uuid

import pytest

pytestmark = pytest.mark.integration

DOC_TEXT = (
    "本基金为股票型基金，投资范围包括国内依法发行的股票、债券、货币市场工具等。"
    "基金主要投资于中证红利低波动指数成分股，追求跟踪标的指数的表现。"
    "风险收益特征：本基金为股票型基金，预期风险和预期收益高于混合型基金、债券型基金和货币市场基金。"
    "投资者应当认真阅读基金合同、招募说明书等信息披露文件，自主判断基金的投资价值，自主做出投资决策。"
)


@pytest.fixture
def upload_service(supabase_client, monkeypatch):
    """真实 DocumentService：移除空替身、连本地库、mock 下载。"""
    import os
    import sys

    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    # 移除 conftest 的空替身，加载真实 document_service（连带 torch 等重依赖）
    sys.modules.pop("server.services.document_service", None)

    from server.storage import supabase_client as sc

    monkeypatch.setattr(sc, "get_supabase", lambda: supabase_client)

    from server.services.document_service import DocumentService

    svc = DocumentService()

    # mock 下载：返回固定文本内容（出网守卫会拦真实 requests.get）
    import requests

    class FakeResponse:
        status_code = 200
        content = DOC_TEXT.encode("utf-8")
        headers = {"content-type": "text/plain"}

    monkeypatch.setattr(requests, "get", lambda url, timeout=30: FakeResponse())
    return svc


def test_process_file_from_edge_完整链路(upload_service, supabase_client, auth_user_id):
    # documents.file_id 有 FK 到 files.id，先建 files 记录
    file_rec = supabase_client.table("files").insert(
        {"user_id": auth_user_id, "name": "红利ETF招募说明书.txt", "type": "file"}
    ).execute().data[0]
    file_id = file_rec["id"]

    document_id = asyncio.run(
        upload_service.process_file_from_edge(
            file_id=file_id,
            user_id=auth_user_id,
            download_url="http://example.com/红利ETF招募说明书.txt",
            doc_type="general_document",
        )
    )

    # documents 记录：状态 ready
    docs = supabase_client.table("documents").select("*").eq("file_id", file_id).execute().data
    assert len(docs) == 1
    assert docs[0]["id"] == document_id
    assert docs[0]["status"] == "ready"

    # document_chunks 写入：含真实嵌入（向量维度 768）
    chunks = supabase_client.table("document_chunks").select("*").eq("document_id", document_id).execute().data
    assert len(chunks) >= 1
    # supabase-py 对 vector 列返回 JSON 字符串，解析后验证 768 维
    emb = chunks[0]["embedding"]
    if isinstance(emb, str):
        import json

        emb = json.loads(emb)
    assert len(emb) == 768
    assert chunks[0]["content"]
