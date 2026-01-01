import sqlite3
import json
from typing import Optional
from server.config.settings import SETTINGS
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class DocumentRepo:
    def __init__(self, db_path: Optional[str] = None):
        logger.debug(f"初始化DocumentRepo，数据库路径: {db_path or SETTINGS.DB_PATH}")
        self.db_path = db_path or SETTINGS.DB_PATH
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
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO documents(id, url, source, text) VALUES (?, ?, ?, ?)",
            (doc_id, url, source, text),
        )
        con.commit()
        con.close()
        logger.debug(f"文档 {doc_id} 保存完成")

    def get(self, doc_id: str):
        logger.debug(f"获取文档，ID: {doc_id}")
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT id, url, source, text FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        con.close()
        logger.debug(f"数据库查询完成")
        
        if not row:
            logger.debug(f"文档 {doc_id} 不存在")
            return None
            
        result = {"id": row[0], "url": row[1], "source": row[2], "text": row[3]}
        logger.debug(f"文档 {doc_id} 获取完成")
        return result