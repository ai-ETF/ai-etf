import json
from typing import Optional
import logging
from server.config.settings import SETTINGS
from server.storage.supabase_client import get_supabase


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class DocumentRepo:
    def __init__(self, db_path: Optional[str] = None):
        logger.debug(f"初始化DocumentRepo")
        self.supabase = get_supabase()
        
        if not self.supabase:
            error_msg = "Supabase客户端初始化失败，请检查环境变量SUPABASE_URL和SUPABASE_SERVICE_ROLE_KEY是否已设置"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        logger.info("使用Supabase作为文档存储")

    def save(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        logger.debug(f"保存文档元数据，ID: {doc_id}, URL: {url}, 来源: {source}, 文本长度: {len(text) if text else 0}")
        
        # 将文档元数据作为document_chunks表中的一个特殊条目保存
        logger.debug("使用Supabase保存文档元数据到document_chunks表")
        try:
            # 创建一个文档元数据条目，只使用存在的字段，为embedding提供适当大小的零向量
            # 根据SETTINGS.EMBED_DIM创建适当维度的零向量（现在是1536维）
            zero_vector = [0.0] * SETTINGS.EMBED_DIM
            logger.debug(f"创建零向量，维度: {len(zero_vector)}")
            
            metadata_entry = {
                "document_id": doc_id,
                "document_name": f"doc_{doc_id}",
                "document_type": "etf_document_metadata",  # 标识这是文档元数据
                "chunk_index": -1,  # 特殊索引表示元数据
                "content": f"URL: {url}\nSource: {source or 'N/A'}\n\n{text[:4000] if text else ''}",  # 将URL和source信息存储在content中
                "embedding": zero_vector,  # 使用正确维度的零向量
                "page_number": 0  # 元数据页码为0
            }
            
            # 插入文档元数据
            response = self.supabase.table("document_chunks").insert(metadata_entry).execute()
            logger.debug(f"文档 {doc_id} 元数据在Supabase中已插入")
        except Exception as e:
            error_msg = f"Supabase保存文档元数据失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get(self, doc_id: str):
        logger.debug(f"获取文档，ID: {doc_id}")
        
        # 从Supabase的document_chunks表获取文档元数据
        logger.debug("从Supabase的document_chunks表获取文档元数据")
        try:
            # 查询chunk_index为-1的条目，这是文档元数据
            response = self.supabase.table("document_chunks").select("*").eq("document_id", doc_id).eq("chunk_index", -1).execute()
            if response.data:
                row = response.data[0]
                # 从content中提取URL和原始文本
                content = row["content"]
                url = ""
                source = None
                text = content
                
                if content.startswith("URL: "):
                    lines = content.split("\n")
                    if len(lines) >= 2:
                        url = lines[0].replace("URL: ", "")
                        if lines[1].startswith("Source: "):
                            source = lines[1].replace("Source: ", "")
                            text = "\n".join(lines[2:]) if len(lines) > 2 else ""
                
                result = {
                    "id": row["document_id"], 
                    "url": url, 
                    "source": source, 
                    "text": text
                }
                logger.debug(f"文档 {doc_id} 元数据获取完成")
                return result
            else:
                logger.debug(f"文档 {doc_id} 在Supabase中不存在")
                return None
        except Exception as e:
            error_msg = f"Supabase获取文档元数据失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)