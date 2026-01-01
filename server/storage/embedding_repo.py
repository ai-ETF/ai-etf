import sqlite3
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
        logger.debug(f"初始化EmbeddingRepo，数据库路径: {db_path or SETTINGS.DB_PATH}")
        self.db_path = db_path or SETTINGS.DB_PATH
        self.supabase = get_supabase()
        
        if self.supabase:
            logger.info("使用Supabase作为嵌入向量存储")
        else:
            logger.info("使用SQLite作为嵌入向量存储")
            self._ensure()

    def _ensure(self):
        logger.debug(f"确保嵌入向量表存在，路径: {self.db_path}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                chunk_id TEXT,
                text TEXT,
                vector TEXT
            )
            """
        )
        con.commit()
        con.close()
        logger.debug("嵌入向量表检查/创建完成")

    def insert_many(self, doc_id: str, items: List[Dict]):
        logger.debug(f"开始批量插入嵌入向量，文档ID: {doc_id}，项目数量: {len(items)}")
        
        if self.supabase:
            # 使用Supabase存储到document_chunks表
            try:
                logger.debug("使用Supabase批量插入到document_chunks表")
                # 准备数据，适配document_chunks表结构
                supabase_items = []
                for i, item in enumerate(items):
                    logger.debug(f"准备第 {i+1} 个项目，块ID: {item.get('chunk_id')}")
                    # 从chunk_id中提取索引信息，如果有的话
                    chunk_index = 0
                    if '.' in item.get("chunk_id", ""):
                        try:
                            chunk_index = int(item["chunk_id"].split('.')[-1])
                        except:
                            chunk_index = 0
                            
                    supabase_items.append({
                        "document_id": doc_id,
                        "document_name": f"doc_{doc_id}",
                        "document_type": "etf_document",  # 默认类型，您可以根据需要调整
                        "chunk_index": chunk_index,
                        "content": item.get("text", ""),
                        "embedding": item.get("vector", []),
                        "page_number": 1  # 默认页码，您可以根据需要调整
                    })
                
                # 批量插入到document_chunks表
                response = self.supabase.table("document_chunks").insert(supabase_items).execute()
                logger.debug(f"批量插入在Supabase中完成，文档ID: {doc_id}，插入数量: {len(response.data) if hasattr(response, 'data') else len(supabase_items)}")
            except Exception as e:
                logger.error(f"Supabase批量插入失败: {str(e)}，回退到SQLite")
                # 回退到SQLite
                self._insert_many_to_sqlite(doc_id, items)
        else:
            # 使用SQLite存储
            self._insert_many_to_sqlite(doc_id, items)

    def _insert_many_to_sqlite(self, doc_id: str, items: List[Dict]):
        """辅助方法：将嵌入向量保存到SQLite"""
        logger.debug(f"使用SQLite批量插入嵌入向量，文档ID: {doc_id}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        
        for i, it in enumerate(items):
            logger.debug(f"插入第 {i+1} 个项目，块ID: {it.get('chunk_id')}")
            cur.execute(
                "INSERT INTO embeddings(doc_id, chunk_id, text, vector) VALUES (?, ?, ?, ?)",
                (doc_id, it.get("chunk_id"), it.get("text"), json.dumps(it.get("vector"))),
            )
            
        con.commit()
        con.close()
        logger.debug(f"批量插入在SQLite中完成，文档ID: {doc_id}")

    def query_all(self, doc_id: Optional[str] = None) -> List[Dict]:
        logger.debug(f"查询嵌入向量，文档ID过滤: {doc_id}")
        
        if self.supabase:
            # 从Supabase的document_chunks表查询
            try:
                logger.debug("从Supabase的document_chunks表查询嵌入向量")
                query = self.supabase.table("document_chunks").select("id, document_id, content, embedding")
                
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
                logger.error(f"Supabase查询失败: {str(e)}，回退到SQLite")
                # 回退到SQLite
                return self._query_all_from_sqlite(doc_id)
        else:
            # 从SQLite查询
            return self._query_all_from_sqlite(doc_id)

    def _query_all_from_sqlite(self, doc_id: Optional[str] = None) -> List[Dict]:
        """辅助方法：从SQLite查询嵌入向量"""
        logger.debug(f"从SQLite查询嵌入向量，文档ID过滤: {doc_id}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        
        if doc_id:
            logger.debug(f"查询特定文档的嵌入向量")
            cur.execute("SELECT id, doc_id, chunk_id, text, vector FROM embeddings WHERE doc_id = ?", (doc_id,))
        else:
            logger.debug(f"查询所有嵌入向量")
            cur.execute("SELECT id, doc_id, chunk_id, text, vector FROM embeddings")
            
        rows = cur.fetchall()
        con.close()
        logger.debug(f"SQLite查询完成，返回 {len(rows)} 行")
        
        out = []
        for i, r in enumerate(rows):
            logger.debug(f"处理第 {i+1} 行数据，块ID: {r[2]}")
            vec = json.loads(r[4]) if r[4] else None
            out.append({"id": r[0], "doc_id": r[1], "chunk_id": r[2], "text": r[3], "vector": vec})
            
        logger.debug(f"SQLite数据处理完成，返回 {len(out)} 个项目")
        return out