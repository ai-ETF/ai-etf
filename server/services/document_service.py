import uuid
import requests
import logging
from server.rag.chunker import split_text
from server.rag.embedder import Embedder
from server.storage.document_repo import DocumentRepo
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class DocumentService:
    """
    文档服务类
    负责处理文档的上传、解析、嵌入和存储
    """
    
    def __init__(self):
        """
        初始化文档服务
        创建文档存储、嵌入存储和嵌入器实例
        """
        logger.debug("初始化文档服务")
        self.doc_repo = DocumentRepo()
        self.emb_repo = EmbeddingRepo()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        logger.debug(f"文档服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}")

    def ingest_document(self, url: str, source: str = None) -> str:
        """
        摄取文档，包括下载、分割、嵌入和存储
        
        参数:
            url: 文档的URL地址
            source: 文档来源（可选）
            
        返回:
            生成的文档ID
            
        异常:
            RuntimeError: 当下载文档失败时抛出
        """
        logger.debug(f"开始处理文档，URL: {url}, 来源: {source}")
        
        # 下载文档
        logger.debug(f"正在下载文档: {url}")
        res = requests.get(url, timeout=30)
        logger.debug(f"下载响应状态码: {res.status_code}")
        
        if res.status_code != 200:
            error_msg = f"下载失败，URL: {url}，状态码: {res.status_code}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        text = None
        ct = res.headers.get("content-type", "")
        logger.debug(f"文档内容类型: {ct}")
        
        # 根据内容类型决定如何处理文档
        if "text" in ct or url.endswith(".txt") or url.endswith(".md") or url.endswith(".html"):
            text = res.text
            logger.debug(f"检测到文本内容，长度: {len(text)}")
        else:
            # 对于非文本内容，存储占位符
            text = f"[binary document downloaded from {url}; size={len(res.content)} bytes]"
            logger.debug(f"检测到非文本内容，使用占位符")

        doc_id = str(uuid.uuid4())
        logger.debug(f"生成文档ID: {doc_id}")
        
        # 保存原始文档
        logger.debug("正在保存文档到存储库")
        self.doc_repo.save(doc_id, url, text, source=source)
        logger.debug("文档保存完成")

        # 分割文本
        logger.debug("开始分割文本")
        chunks = split_text(text, chunk_size=800, overlap=120)
        logger.debug(f"文本分割完成，共生成 {len(chunks)} 个块")

        items = []
        for i, c in enumerate(chunks):
            logger.debug(f"正在处理第 {i+1} 个文本块，长度: {len(c)}")
            # 为每个文本块生成嵌入向量
            vector = self.embedder.embed_text(c)
            logger.debug(f"文本块嵌入向量生成完成，向量维度: {len(vector)}")
            items.append({"chunk_id": f"{doc_id}.{i}", "text": c, "vector": vector})

        # 持久化存储嵌入向量
        logger.debug(f"开始存储 {len(items)} 个嵌入向量")
        self.emb_repo.insert_many(doc_id, items)
        logger.debug("嵌入向量存储完成")

        logger.debug(f"文档处理完成，返回文档ID: {doc_id}")
        return doc_id