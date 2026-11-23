import logging
from sentence_transformers import SentenceTransformer
import os
from typing import List


logger = logging.getLogger(__name__)


class Embedder:
    """
    基于本地模型的嵌入器
    
    使用本地text2vec模型进行真正的文本向量化
    """
    
    def __init__(self, dim: int = 768):
        """
        初始化嵌入器
        
        参数:
            dim: 向量维度，默认为768（与text2vec-base-chinese模型匹配）
        """
        logger.debug(f"初始化嵌入器，维度: {dim}")
        self.dim = dim
        
        # 检查本地模型是否存在
        local_model_path = "./local_models/text2vec-base-chinese"
        if os.path.exists(local_model_path):
            logger.info(f"从本地路径加载模型: {local_model_path}")
            self.model = SentenceTransformer(local_model_path)
        else:
            logger.info("本地模型不存在，尝试从HuggingFace下载模型...")
            self.model = SentenceTransformer('shibing624/text2vec-base-chinese')
        
        logger.debug("嵌入器初始化完成")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入多个文本
        
        参数:
            texts: 文本列表
            
        返回:
            向量列表，每个文本对应一个向量
        """
        logger.debug(f"开始批量嵌入 {len(texts)} 个文本")
        embeddings = self.model.encode(texts).tolist()
        logger.debug(f"批量嵌入完成，结果数量: {len(embeddings)}")
        
        # 验证维度
        for i, emb in enumerate(embeddings):
            if len(emb) != self.dim:
                logger.error(f"向量维度不匹配！索引 {i}: 实际 {len(emb)}, 期望 {self.dim}")
        
        return embeddings

    def embed_text(self, text: str) -> List[float]:
        """
        嵌入单个文本
        
        参数:
            text: 输入文本
            
        返回:
            对应的向量
        """
        logger.debug(f"开始嵌入单个文本，长度: {len(text)}")
        embedding = self.model.encode([text])[0].tolist()
        logger.debug(f"文本嵌入完成，向量维度: {len(embedding)}")
        
        # 验证维度
        if len(embedding) != self.dim:
            logger.error(f"向量维度不匹配！实际: {len(embedding)}, 期望: {self.dim}")
        
        return embedding