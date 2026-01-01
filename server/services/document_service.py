import uuid
import requests
from server.rag.chunker import split_text
from server.rag.embedder import Embedder
from server.storage.document_repo import DocumentRepo
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS


class DocumentService:
    def __init__(self):
        self.doc_repo = DocumentRepo()
        self.emb_repo = EmbeddingRepo()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)

    def ingest_document(self, url: str, source: str = None) -> str:
        # download
        res = requests.get(url, timeout=30)
        if res.status_code != 200:
            raise RuntimeError(f"failed to download {url}: {res.status_code}")

        text = None
        ct = res.headers.get("content-type", "")
        if "text" in ct or url.endswith(".txt") or url.endswith(".md") or url.endswith(".html"):
            text = res.text
        else:
            # fallback: store a placeholder
            text = f"[binary document downloaded from {url}; size={len(res.content)} bytes]"

        doc_id = str(uuid.uuid4())
        # save original
        self.doc_repo.save(doc_id, url, text, source=source)

        # chunk
        chunks = split_text(text, chunk_size=800, overlap=120)

        items = []
        for i, c in enumerate(chunks):
            items.append({"chunk_id": f"{doc_id}.{i}", "text": c, "vector": self.embedder.embed_text(c)})

        # persist embeddings
        self.emb_repo.insert_many(doc_id, items)

        return doc_id
