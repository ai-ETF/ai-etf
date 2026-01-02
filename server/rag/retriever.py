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


def cosine(a, b):
    """
    计算两个向量的余弦相似度
    
    参数:
        a, b: 两个向量
        
    返回:
        余弦相似度值，范围在-1到1之间
    """
    logger.debug(f"计算余弦相似度，向量a长度: {len(a)}, 向量b长度: {len(b)}")
    na = _norm(a)
    nb = _norm(b)
    logger.debug(f"向量a模长: {na}, 向量b模长: {nb}")
    
    if na == 0 or nb == 0:
        logger.debug("其中一个向量为零向量，余弦相似度为0")
        return 0.0
    
    result = _dot(a, b) / (na * nb)
    logger.debug(f"余弦相似度计算完成，结果: {result}")
    return result


class Retriever:
    def __init__(self, embedding_repo):
        self.embedding_repo = embedding_repo

    def retrieve(self, query_vector, top_k=5, doc_id=None):
        return self.embedding_repo.match_by_vector(
            query_vector=query_vector,
            top_k=top_k,
            doc_id=doc_id
        )
