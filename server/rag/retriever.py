from typing import List, Dict
import math
import logging
from server.storage.embedding_repo import EmbeddingRepo


# 配置日志
logging.basicConfig(level=logging.DEBUG)
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

    def retrieve(self, query_vector, top_k=5, doc_id=None):
        # 调用数据库的match_chunks函数
        results = self.embedding_repo.match_by_vector(
            query_vector=query_vector,
            top_k=top_k,
            doc_id=doc_id
        )
        
        # 将数据库返回的字段映射到应用所需的字段
        mapped_results = []
        for result in results:
            mapped_result = {
                "chunk_id": result.get("chunk_id"),
                "text": result.get("content"),  # 数据库返回的是content字段
                "score": result.get("similarity"),  # 数据库返回的是similarity字段，映射为score
                "page_number": result.get("page_number"),
                "chunk_index": result.get("chunk_index")
            }
            mapped_results.append(mapped_result)
        
        return mapped_results