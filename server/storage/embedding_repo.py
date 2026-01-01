import json
from typing import Optional, List, Dict
import logging
from server.config.settings import SETTINGS
from server.storage.supabase_client import get_supabase


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class EmbeddingRepo:
    def __init__(self, db_path: Optional[str] = None):
        logger.debug(f"初始化EmbeddingRepo")
        self.supabase = get_supabase()
        
        if not self.supabase:
            error_msg = "Supabase客户端初始化失败，请检查环境变量SUPABASE_URL和SUPABASE_SERVICE_ROLE_KEY是否已设置"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        logger.info("使用Supabase作为嵌入向量存储")

    def insert_many(self, doc_id: str, items: List[Dict]):
        logger.debug(f"开始批量插入嵌入向量，文档ID: {doc_id}，项目数量: {len(items)}")
        
        # 使用Supabase存储到document_chunks表
        logger.debug("使用Supabase批量插入到document_chunks表")
        try:
            # 准备数据，适配document_chunks表结构
            supabase_items = []
            for i, item in enumerate(items):
                logger.debug(f"准备第 {i+1} 个项目，块ID: {item.get('chunk_id')}")
                # 从chunk_id中提取索引信息，如果有的话
                chunk_index = i  # 使用循环索引作为chunk_index
                
                # 确保向量数据存在且格式正确
                vector = item.get("vector", [])
                if not vector or len(vector) == 0:
                    # 如果向量为空，使用零向量
                    vector = [0.0] * SETTINGS.EMBED_DIM
                
                supabase_items.append({
                    "document_id": doc_id,
                    "document_name": f"doc_{doc_id}",
                    "document_type": "etf_document_chunk",  # 标识这是文档块
                    "chunk_index": chunk_index,
                    "content": item.get("text", ""),
                    "embedding": vector,  # 确保向量数据正确传递
                    "page_number": chunk_index // 10 + 1  # 基于索引估算页码
                })
            
            # 批量插入到document_chunks表
            response = self.supabase.table("document_chunks").insert(supabase_items).execute()
            logger.debug(f"批量插入在Supabase中完成，文档ID: {doc_id}，插入数量: {len(response.data) if hasattr(response, 'data') else len(supabase_items)}")
        except Exception as e:
            error_msg = f"Supabase批量插入失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def query_all(self, doc_id: Optional[str] = None) -> List[Dict]:
        logger.debug(f"查询嵌入向量，文档ID过滤: {doc_id}")
        
        # 从Supabase的document_chunks表查询
        logger.debug("从Supabase的document_chunks表查询嵌入向量")
        try:
            # 排除chunk_index为-1的元数据条目，只获取实际的文本块
            query = self.supabase.table("document_chunks").select("id, document_id, content, embedding").neq("chunk_index", -1)
            
            if doc_id:
                logger.debug(f"查询特定文档的嵌入向量")
                query = query.eq("document_id", doc_id)
            else:
                logger.debug(f"查询所有嵌入向量")
            
            response = query.execute()
            rows = response.data
            logger.debug(f"Supabase查询完成，返回 {len(rows)} 行")
            
            out = []
            for i, r in enumerate(rows):
                logger.debug(f"处理第 {i+1} 行数据，文档ID: {r['document_id']}")
                # embedding字段在Supabase中是向量格式，直接使用
                embedding = r['embedding']
                out.append({
                    "id": r['id'], 
                    "doc_id": r['document_id'], 
                    "chunk_id": f"{r['document_id']}.{r.get('chunk_index', 0)}", 
                    "text": r['content'], 
                    "vector": embedding
                })
                
            logger.debug(f"Supabase数据处理完成，返回 {len(out)} 个项目")
            return out
        except Exception as e:
            error_msg = f"Supabase查询失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)