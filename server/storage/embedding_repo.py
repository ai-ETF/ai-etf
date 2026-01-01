import sqlite3
import json
from typing import Optional, List, Dict
from server.config.settings import SETTINGS


class EmbeddingRepo:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SETTINGS.DB_PATH
        self._ensure()

    def _ensure(self):
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

    def insert_many(self, doc_id: str, items: List[Dict]):
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        for it in items:
            cur.execute(
                "INSERT INTO embeddings(doc_id, chunk_id, text, vector) VALUES (?, ?, ?, ?)",
                (doc_id, it.get("chunk_id"), it.get("text"), json.dumps(it.get("vector"))),
            )
        con.commit()
        con.close()

    def query_all(self, doc_id: Optional[str] = None) -> List[Dict]:
        con = sqlite3.connect(self.db_path)
        cur = con.cursor()
        if doc_id:
            cur.execute("SELECT id, doc_id, chunk_id, text, vector FROM embeddings WHERE doc_id = ?", (doc_id,))
        else:
            cur.execute("SELECT id, doc_id, chunk_id, text, vector FROM embeddings")
        rows = cur.fetchall()
        con.close()
        out = []
        for r in rows:
            vec = json.loads(r[4]) if r[4] else None
            out.append({"id": r[0], "doc_id": r[1], "chunk_id": r[2], "text": r[3], "vector": vec})
        return out
