import json
import logging
from typing import Optional
from server.storage.supabase_client import get_supabase


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class DocumentRepo:
    def __init__(self, db_path: Optional[str] = None):
        logger.debug("初始化DocumentRepo")
        self.supabase = get_supabase()
        
        if not self.supabase:
            error_msg = "Supabase客户端初始化失败，请检查环境变量SUPABASE_URL和SUPABASE_SERVICE_ROLE_KEY是否已设置"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        logger.info("使用Supabase作为文档存储")

    def save(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        logger.debug(f"保存文档，ID: {doc_id}, URL: {url}, 来源: {source}, 文本长度: {len(text) if text else 0}")
        
        # 使用Supabase存储
        logger.debug("使用Supabase保存文档")
        try:
            # 检查文档是否已存在
            existing_doc = self.supabase.table("documents").select("id").eq("id", doc_id).execute()
            
            data = {
                "id": doc_id, 
                "url": url, 
                "source": source, 
                "text": text
            }
            
            if existing_doc.data:
                # 文档已存在，执行更新操作
                response = self.supabase.table("documents").update(data).eq("id", doc_id).execute()
                logger.debug(f"文档 {doc_id} 在Supabase中已更新")
            else:
                # 文档不存在，执行插入操作
                response = self.supabase.table("documents").insert(data).execute()
                logger.debug(f"文档 {doc_id} 在Supabase中已插入")
        except Exception as e:
            error_msg = f"Supabase保存失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get(self, doc_id: str):
        logger.debug(f"获取文档，ID: {doc_id}")
        
        # 从Supabase获取
        logger.debug("从Supabase获取文档")
        try:
            response = self.supabase.table("documents").select("*").eq("id", doc_id).execute()
            if response.data:
                row = response.data[0]
                result = {
                    "id": row["id"], 
                    "url": row["url"], 
                    "source": row["source"], 
                    "text": row["text"]
                }
                logger.debug(f"文档 {doc_id} Supabase获取完成")
                return result
            else:
                logger.debug(f"文档 {doc_id} 在Supabase中不存在")
                return None
        except Exception as e:
            error_msg = f"Supabase获取失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)