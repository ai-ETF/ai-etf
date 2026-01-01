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
    """
    检索器类
    用于从向量数据库中检索与查询向量最相似的文本块
    """
    
    def __init__(self, embedding_repo):
        """
        初始化检索器
        
        参数:
            embedding_repo: 嵌入向量存储库实例
        """
        logger.debug("初始化检索器")
        self.embedding_repo = embedding_repo
        logger.debug("检索器初始化完成")

    def retrieve(self, query_vector: List[float], top_k: int = 5, doc_id: str = None) -> List[Dict]:
        """
        检索与查询向量最相似的文本块
        
        参数:
            query_vector: 查询向量
            top_k: 返回的最相似文本块数量
            doc_id: 可选，限制检索范围到特定文档
            
        返回:
            包含相似度得分和文本块信息的字典列表
        """
        logger.debug(f"开始检索，查询向量维度: {len(query_vector)}, top_k: {top_k}, 文档ID: {doc_id}")
        
        # embedding_repo应该提供query_all()方法，返回包含'vector'和'text'的字典
        rows = self.embedding_repo.query_all(doc_id=doc_id)
        logger.debug(f"从存储库获取 {len(rows)} 个向量进行比较")
        
        scored = []
        for r in rows:
            v = r.get("vector")
            if v is None:
                logger.warning(f"跳过向量为None的文本块: {r.get('chunk_id')}")
                continue
            logger.debug(f"计算与向量 {r.get('chunk_id')} 的相似度")
            score = cosine(query_vector, v)
            scored.append((score, r))
        
        # 按相似度得分降序排列
        logger.debug("开始排序")
        scored.sort(key=lambda x: x[0], reverse=True)
        logger.debug("排序完成")
        
        # 返回前top_k个结果，合并得分和原始数据
        top_results = scored[:top_k]
        logger.debug(f"选取前 {len(top_results)} 个结果")
        
        result = [dict(score=s, **r) for s, r in top_results]
        logger.debug(f"检索完成，返回 {len(result)} 个结果")
        return result