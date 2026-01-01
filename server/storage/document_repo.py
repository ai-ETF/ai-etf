import sqlite3
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
        logger.debug(f"初始化DocumentRepo，数据库路径: {db_path or SETTINGS.DB_PATH}")
        self.db_path = db_path or SETTINGS.DB_PATH
        self.supabase = get_supabase()
        
        if self.supabase:
            logger.info("使用Supabase作为文档存储")
        else:
            logger.info("使用SQLite作为文档存储")
            self._ensure()

    def _ensure(self):
        logger.debug(f"确保数据库表存在，路径: {self.db_path}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documents(
                id TEXT PRIMARY KEY,
                url TEXT,
                source TEXT,
                text TEXT
            )
            """
        )
        con.commit()
        con.close()
        logger.debug("数据库表检查/创建完成")

    def save(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        logger.debug(f"保存文档，ID: {doc_id}, URL: {url}, 来源: {source}, 文本长度: {len(text) if text else 0}")
        
        if self.supabase:
            # 使用Supabase存储
            try:
                logger.debug("使用Supabase保存文档")
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
                logger.error(f"Supabase保存失败: {str(e)}，回退到SQLite")
                # 回退到SQLite
                self._save_to_sqlite(doc_id, url, text, source)
        else:
            # 使用SQLite存储
            self._save_to_sqlite(doc_id, url, text, source)

    def _save_to_sqlite(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        """辅助方法：将文档保存到SQLite"""
        logger.debug(f"使用SQLite保存文档 {doc_id}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO documents(id, url, source, text) VALUES (?, ?, ?, ?)",
            (doc_id, url, source, text),
        )
        con.commit()
        con.close()
        logger.debug(f"文档 {doc_id} SQLite保存完成")

    def get(self, doc_id: str):
        logger.debug(f"获取文档，ID: {doc_id}")
        
        if self.supabase:
            # 从Supabase获取
            try:
                logger.debug("从Supabase获取文档")
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
                logger.error(f"Supabase获取失败: {str(e)}，回退到SQLite")
                # 回退到SQLite
                return self._get_from_sqlite(doc_id)
        else:
            # 从SQLite获取
            return self._get_from_sqlite(doc_id)

    def _get_from_sqlite(self, doc_id: str):
        """辅助方法：从SQLite获取文档"""
        logger.debug(f"从SQLite获取文档 {doc_id}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT id, url, source, text FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        con.close()
        logger.debug(f"SQLite查询完成")
        
        if not row:
            logger.debug(f"文档 {doc_id} 在SQLite中不存在")
            return None
            
        result = {"id": row[0], "url": row[1], "source": row[2], "text": row[3]}
        logger.debug(f"文档 {doc_id} SQLite获取完成")
        return result