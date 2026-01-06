# server/services/document_service.py
import uuid
import requests
import logging
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
from server.rag.chunker import split_text
from server.rag.embedder import Embedder
from server.storage.document_repo import DocumentRepo
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS
from server.agents.document_agent import DocumentAgent

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DocumentProcessor(ABC):
    """文档处理器的抽象基类，定义了处理流程的骨架"""
    
    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        
    def process(self, content: bytes, file_extension: str, doc_type: str = "general_document") -> Tuple[str, List[str], List[List[float]]]:
        """
        处理文档的主流程模板方法
        返回: (提取的文本, 文本块列表, 向量列表)
        """
        logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        logger.debug(f"开始使用 {self.__class__.__name__} 处理文档")
        
        # 1. 内容提取 (由子类实现)
        text = self._extract_content(content, file_extension)
        logger.debug(f"✅ 内容提取完成，字符数: {len(text)}")
        
        # 2. 文本分块
        logger.debug("开始文本分块...")
        # 根据文档类型调整分块策略
        if doc_type == "financial_report":
            chunks = split_text(text, chunk_size=1000, overlap=200)  # 财务报告使用更大的块大小
        elif doc_type == "etf_report":
            chunks = split_text(text, chunk_size=900, overlap=150)  # ETF报告使用适中的块大小
        elif doc_type == "regulatory_document":
            chunks = split_text(text, chunk_size=700, overlap=150)  # 法规文档使用较小的块大小以保持条款完整性
        else:
            chunks = split_text(text, chunk_size=800, overlap=120)  # 默认分块策略
        
        logger.debug(f"✅ 文本分块完成，共 {len(chunks)} 块")
        
        # 3. 向量化
        logger.debug("开始生成文本向量...")
        vectors = []
        for i, chunk in enumerate(chunks):
            vector = self.embedder.embed_text(chunk)
            vectors.append(vector)
        logger.debug(f"✅ 向量生成完成，共 {len(vectors)} 个向量")
        
        logger.debug("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        return text, chunks, vectors
    
    @abstractmethod
    def _extract_content(self, content: bytes, file_extension: str) -> str:
        """从原始内容中提取文本 (子类必须实现)"""
        pass
    
    def _log_chunks_preview(self, chunks: List[str], limit: int = 5, preview_len: int = 200):
        """记录文本块预览"""
        logger.debug("📄 文本块预览 (前5个，限制200字符):")
        for i, chunk in enumerate(chunks[:limit]):
            preview = chunk[:preview_len] + ("..." if len(chunk) > preview_len else "")
            logger.debug(f"  块 {i+1}/{len(chunks)}: {preview}")
    
    def _log_vectors_preview(self, vectors: List[List[float]], limit: int = 5, preview_dims: int = 200):
        """记录向量预览"""
        logger.debug("🧮 向量预览 (前5个，限制200维度):")
        for i, vector in enumerate(vectors[:limit]):
            preview = vector[:preview_dims]
            logger.debug(f"  向量 {i+1}/{len(vectors)} 前{len(preview)}维: {preview[:10]}..." if len(preview) > 10 else f"  向量 {i+1}/{len(vectors)}: {preview}")


class PDFProcessor(DocumentProcessor):
    """PDF文档处理器"""
    
    def _extract_content(self, content: bytes, file_extension: str) -> str:
        """从PDF文件中提取文本"""
        logger.debug("🔄 调用PDF工具处理...")
        try:
            import pypdf
            from io import BytesIO
            
            text = ""
            pdf_file = BytesIO(content)
            pdf_reader = pypdf.PdfReader(pdf_file)
            
            logger.debug(f"📑 PDF页数: {len(pdf_reader.pages)}")
            for page_num, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                if page_num < 2:  # 预览前3页的文本长度
                    logger.debug(f"  第{page_num+1}页提取字符数: {len(page_text)}")
            
            return text
        except ImportError:
            logger.error("❌ pypdf库未安装，请运行: pip install pypdf")
            raise
        except Exception as e:
            logger.error(f"❌ PDF处理失败: {e}")
            return f"[PDF处理错误: {str(e)}]"


class TextProcessor(DocumentProcessor):
    """文本文件处理器"""
    
    def _extract_content(self, content: bytes, file_extension: str) -> str:
        """直接从字节内容解码为文本"""
        logger.debug("🔄 直接提取文本信息...")
        try:
            # 尝试UTF-8解码，失败则尝试其他编码
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                text = content.decode('gbk', errors='ignore')
                logger.debug("⚠️  UTF-8解码失败，使用GBK解码")
            
            # 记录文本统计信息
            lines = text.split('\n')
            logger.debug(f"📊 文本统计: {len(text)} 字符, {len(lines)} 行")
            if lines:
                logger.debug(f"  首行预览: {lines[0][:100]}...")
            
            return text
        except Exception as e:
            logger.error(f"❌ 文本提取失败: {e}")
            return f"[文本提取错误: {str(e)}]"


class DocumentService:
    """
    重构后的文档服务类
    职责: 协调文档处理流程，管理存储
    """
    
    def __init__(self):
        logger.debug("🚀 初始化文档服务")
        self.doc_repo = DocumentRepo()
        self.emb_repo = EmbeddingRepo()
        self.embedder = Embedder(dim=SETTINGS.EMBED_DIM)
        self.document_agent = DocumentAgent()  # 添加DocumentAgent实例
        
        # 创建文档存储目录：如果有的话会直接跳过
        self.doc_dir = Path("docs")
        self.doc_dir.mkdir(exist_ok=True)
        
        # 初始化处理器映射
        self._init_processors()
        
        logger.debug(f"✅ 文档服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}")

    def _init_processors(self):
        """初始化文档处理器映射"""
        self.processors = {
            '.pdf': PDFProcessor(self.embedder),
            '.txt': TextProcessor(self.embedder),
            '.md': TextProcessor(self.embedder),
            '.html': TextProcessor(self.embedder),
            '.json': TextProcessor(self.embedder),
            '.xml': TextProcessor(self.embedder),
            '.csv': TextProcessor(self.embedder),
        }
        logger.debug(f"📋 已注册处理器: {list(self.processors.keys())}")

    def ingest_document(self, url: str, source: str = None) -> str:
        """
        摄取文档的主入口
        清晰的功能步骤:
        1. 下载文档
        2. 判断文档类型
        3. 更改文档拓展名
        4. 保存到本地
        5. 根据类型调用对应处理器
        6. 分块处理 + 向量处理
        7. 存储结果
        """
        logger.info("=" * 60)
        logger.info(f"📥 开始处理文档: {url}")
        
        # === 步骤1: 下载文档 ===
        logger.debug("1️⃣ 下载文档...")
        content, content_type = self._download_document(url)
        logger.debug(f"  下载完成，大小: {len(content)} 字节, 类型: {content_type}")
        
        # === 步骤2: 判断文档类型 ===
        logger.debug("2️⃣ 判断文档类型...")
        file_extension = self._determine_file_extension(url, content_type, content)
        processor = self._get_processor(file_extension)
        logger.debug(f"  判断结果: 扩展名={file_extension}, 处理器={processor.__class__.__name__}")
        
        # === 步骤3&4: 更改拓展名并保存到本地 ===
        logger.debug("3️⃣&4️⃣ 保存到本地...")
        local_path = self._save_to_local(content, file_extension)
        logger.debug(f"  已保存到: {local_path}")
        
        # === 步骤5: 使用DocumentAgent分析文档类型和结构 ===
        logger.debug("5️⃣ 使用DocumentAgent分析文档...")
        text_content = self._decode_content(content)  # 先解码内容以供分析
        analysis_result = self.document_agent.analyze(text_content)
        doc_type = analysis_result["document_type"]
        logger.debug(f"  文档类型分析结果: {doc_type}，置信度: {analysis_result['confidence']:.2f}")
        
        # === 步骤6: 根据文档类型调用对应处理器处理文档内容 ===
        logger.debug("6️⃣ 调用处理器处理文档内容...")
        text, chunks, vectors = processor.process(content, file_extension, doc_type)
        
        # === 步骤7: 分块处理 + 向量处理 ===
        logger.debug("7️⃣ 输出处理结果预览...")
        processor._log_chunks_preview(chunks)
        processor._log_vectors_preview(vectors)
        
        # === 步骤8: 存储结果到Supabase的document_chunks表 ===
        logger.debug("8️⃣ 存储处理结果...")
        doc_id = self._store_results(chunks, vectors, doc_type, analysis_result)
        
        # 清理临时文件
        self._cleanup_temp_file(local_path)
        
        logger.info(f"✅ 文档处理完成! ID: {doc_id}")
        logger.info("=" * 60)
        return doc_id
    
    def _decode_content(self, content: bytes) -> str:
        """解码字节内容为字符串，用于DocumentAgent分析"""
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            return content.decode('gbk', errors='ignore')

    def _download_document(self, url: str) -> Tuple[bytes, str]:
        """下载文档并返回内容和类型"""
        try:
            res = requests.get(url, timeout=30)
            if res.status_code != 200:
                raise RuntimeError(f"下载失败，状态码: {res.status_code}")
            return res.content, res.headers.get('content-type', '')
        except Exception as e:
            logger.error(f"❌ 文档下载失败: {e}")
            raise
    
    def _determine_file_extension(self, url: str, content_type: str, content: bytes) -> str:
        """综合判断文档类型"""
        # 方法1: 从URL路径获取扩展名
        url_ext = Path(url).suffix.lower()
        if url_ext and len(url_ext) <= 10:  # 合理的扩展名长度
            logger.debug(f"  从URL获取扩展名: {url_ext}")
            return url_ext
        
        # 方法2: 从Content-Type推断
        content_type_map = {
            'application/pdf': '.pdf',
            'text/plain': '.txt',
            'text/html': '.html',
            'application/json': '.json',
            'application/xml': '.xml',
            'text/xml': '.xml',
            'text/csv': '.csv',
            'text/markdown': '.md',
        }
        if content_type in content_type_map:
            ext = content_type_map[content_type]
            logger.debug(f"  从Content-Type推断扩展名: {ext}")
            return ext
        
        # 方法3: 通过文件魔数判断 (最可靠)
        file_signatures = {
            b'%PDF': '.pdf',
            b'\x50\x4B\x03\x04': '.docx',  # ZIP格式，可能是docx
            b'\x25\x50\x44\x46': '.pdf',   # 另一种PDF签名
        }
        
        for signature, ext in file_signatures.items():
            if content[:4].startswith(signature):
                logger.debug(f"  通过文件签名判断扩展名: {ext}")
                return ext
        
        # 默认值
        logger.warning(f"⚠️  无法确定文档类型，使用默认扩展名 .dat")
        return '.dat'
    
    def _get_processor(self, file_extension: str) -> DocumentProcessor:
        """根据扩展名获取处理器"""
        processor = self.processors.get(file_extension.lower())
        if not processor:
            logger.warning(f"⚠️  没有找到 {file_extension} 的处理器，使用文本处理器作为后备")
            return TextProcessor(self.embedder)
        return processor
    
    def _save_to_local(self, content: bytes, file_extension: str) -> Path:
        """保存文档到本地"""
        filename = f"temp_doc_{uuid.uuid4()}{file_extension}"
        filepath = self.doc_dir / filename
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        return filepath
    
    def _store_results(self, chunks: List[str], vectors: List[List[float]], doc_type: str, analysis_result: dict) -> str:
        """存储处理结果到数据库，仅存储向量块"""
        doc_id = str(uuid.uuid4())
        
        # 准备嵌入向量数据
        items = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            items.append({
                "chunk_id": f"{doc_id}.{i}",
                "text": chunk,
                "vector": vector,
                "document_type": doc_type,
                "document_name": f"doc_{doc_id}",
                "chunk_index": i
            })
        
        # 批量插入嵌入向量
        self.emb_repo.insert_many(doc_id, items)
        
        return doc_id
    
    def _cleanup_temp_file(self, filepath: Path):
        """清理临时文件"""
        # try:
        #     if filepath.exists():
        #         os.unlink(filepath)
        #         logger.debug(f"🗑️  已清理临时文件: {filepath}")
        # except Exception as e:
        #     logger.warning(f"⚠️  清理临时文件失败: {e}")