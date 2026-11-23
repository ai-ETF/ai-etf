from typing import List, Dict
import math
import logging
from server.storage.embedding_repo import EmbeddingRepo


logger = logging.getLogger(__name__)


def _dot(a, b):
    """
    计算两个向量的点积
    
    参数:
        a, b: 两个向量
        
    返回:
        点积结果
    """
    logger.debug(f"计算向量点积，向量a长度: {len(a)}, 向量b长度: {len(b)}")
    result = sum(x * y for x, y in zip(a, b))
    logger.debug(f"点积计算完成，结果: {result}")
    return result


def _norm(a):
    """
    计算向量的模长（欧几里得范数）
    
    参数:
        a: 输入向量
        
    返回:
        向量的模长
    """
    logger.debug(f"计算向量模长，向量长度: {len(a)}")
    result = math.sqrt(sum(x * x for x in a))
    logger.debug(f"向量模长计算完成，结果: {result}")
    return result



class Retriever:
    def __init__(self, embedding_repo):
        self.embedding_repo = embedding_repo

    def _map_dense_results(self, results: List[Dict]) -> List[Dict]:
        mapped_results = []
        for result in results or []:
            mapped_result = {
                "chunk_id": result.get("chunk_id") or result.get("id"),
                "content": result.get("content") or result.get("text", ""),
                "similarity": result.get("similarity", 0.0),
                "page_number": result.get("page_number"),
                "chunk_index": result.get("chunk_index"),
                "doc_name": result.get("document_name", "未知文档"),
                "doc_type": result.get("document_type") or result.get("doc_type", "other"),
                "document_id": result.get("document_id"),
            }
            mapped_results.append(mapped_result)
        return mapped_results

    def _map_sparse_results(self, results: List[Dict]) -> List[Dict]:
        mapped_results = []
        for result in results or []:
            sparse_score = float(result.get("sparse_score", result.get("keyword_hits", 0.0)))
            mapped_result = {
                "chunk_id": result.get("chunk_id") or result.get("id"),
                "content": result.get("content", ""),
                "similarity": sparse_score,
                "page_number": result.get("page_number"),
                "chunk_index": result.get("chunk_index"),
                "doc_name": result.get("document_name", "未知文档"),
                "doc_type": result.get("doc_type", "other"),
                "document_id": result.get("document_id"),
                "keyword_hits": result.get("keyword_hits", 0),
                "sparse_score": sparse_score,
            }
            mapped_results.append(mapped_result)
        return mapped_results

    def _rrf_fuse(self, dense_results: List[Dict], sparse_results: List[Dict], top_k: int) -> List[Dict]:
        """Reciprocal Rank Fusion: score = sum(1 / (k + rank))."""
        k = 60
        fused_map: Dict[str, Dict] = {}

        for rank, item in enumerate(dense_results, start=1):
            chunk_id = item.get("chunk_id")
            if not chunk_id:
                continue
            if chunk_id not in fused_map:
                fused_map[chunk_id] = dict(item)
                fused_map[chunk_id]["rrf_score"] = 0.0
            fused_map[chunk_id]["rrf_score"] += 1.0 / (k + rank)

        for rank, item in enumerate(sparse_results, start=1):
            chunk_id = item.get("chunk_id")
            if not chunk_id:
                continue
            if chunk_id not in fused_map:
                fused_map[chunk_id] = dict(item)
                fused_map[chunk_id]["rrf_score"] = 0.0
            fused_map[chunk_id]["rrf_score"] += 1.0 / (k + rank)

        fused_results = sorted(
            fused_map.values(),
            key=lambda row: row.get("rrf_score", 0.0),
            reverse=True,
        )
        return fused_results[:top_k]

    def retrieve(self, query_vector, top_k=5, doc_id=None, query_text: str = ""):
        dense_raw_results = self.embedding_repo.match_by_vector(
            query_vector=query_vector,
            top_k=max(top_k, 50),
            doc_id=doc_id
        )

        dense_results = self._map_dense_results(dense_raw_results)

        sparse_results: List[Dict] = []
        if query_text:
            sparse_raw_results = self.embedding_repo.match_by_keywords(
                query_text=query_text,
                top_k=max(top_k, 50),
                doc_id=doc_id,
            )
            sparse_results = self._map_sparse_results(sparse_raw_results)

        logger.debug(
            f"Hybrid 检索候选: dense={len(dense_results)}, sparse={len(sparse_results)}, top_k={top_k}"
        )

        if sparse_results:
            fused_results = self._rrf_fuse(dense_results, sparse_results, top_k=top_k)
            logger.debug(f"RRF 融合完成，返回 {len(fused_results)} 条结果")
            return fused_results

        logger.debug("未命中 sparse 候选，回退 dense 结果")
        return dense_results[:top_k]