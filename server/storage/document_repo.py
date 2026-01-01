import sqlite3
import json
from typing import Optional
from server.config.settings import SETTINGS


class DocumentRepo:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SETTINGS.DB_PATH
        self._ensure()

    def _ensure(self):
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

    def save(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO documents(id, url, source, text) VALUES (?, ?, ?, ?)",
            (doc_id, url, source, text),
        )
        con.commit()
        con.close()

    def get(self, doc_id: str):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        cur.execute("SELECT id, url, source, text FROM documents WHERE id = ?", (doc_id,))
        row = cur.fetchone()
        con.close()
        if not row:
            return None
        return {"id": row[0], "url": row[1], "source": row[2], "text": row[3]}
