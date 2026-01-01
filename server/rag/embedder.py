import hashlib
from typing import List
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Embedder:
    """
    确定性轻量级嵌入器
    
    注意：这是一个占位实现，使用哈希函数生成向量。
    在生产环境中应替换为真正的嵌入模型（如sentence-transformers）。
    """
    
    def __init__(self, dim: int = 128):
        """
        初始化嵌入器
        
        参数:
            dim: 向量维度，默认为128
        """
        logger.debug(f"初始化嵌入器，维度: {dim}")
        self.dim = dim
        logger.debug("嵌入器初始化完成")

    def _hash_vector(self, text: str) -> List[float]:
        """
        使用SHA256哈希函数将文本转换为向量
        
        参数:
            text: 输入文本
            
        返回:
            长度为dim的浮点数列表，值范围在-1到1之间
        """
        logger.debug(f"开始将文本转换为向量，文本长度: {len(text)}")
        h = hashlib.sha256(text.encode("utf-8")).digest()
        logger.debug(f"SHA256哈希生成完成，哈希长度: {len(h)}")
        
        vec = []
        for i in range(self.dim):
            byte = h[i % len(h)]
            # 将0-255映射到-1到1
            value = (byte / 255.0) * 2 - 1
            vec.append(value)
            
        logger.debug(f"向量转换完成，维度: {len(vec)}")
        return vec

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入多个文本
        
        参数:
            texts: 文本列表
            
        返回:
            向量列表，每个文本对应一个向量
        """
        logger.debug(f"开始批量嵌入 {len(texts)} 个文本")
        result = [self._hash_vector(t) for t in texts]
        logger.debug(f"批量嵌入完成，结果数量: {len(result)}")
        return result

    def embed_text(self, text: str) -> List[float]:
        """
        嵌入单个文本
        
        参数:
            text: 输入文本
            
        返回:
            对应的向量
        """
        logger.debug(f"开始嵌入单个文本，长度: {len(text)}")
        result = self._hash_vector(text)
        logger.debug(f"文本嵌入完成，向量维度: {len(result)}")
        return result