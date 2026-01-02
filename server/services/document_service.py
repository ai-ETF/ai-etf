# server/services/document_service.py
import uuid
import requests
import logging
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse
import tempfile
from server.rag.chunker import split_text
from server.rag.embedder import Embedder
from server.storage.document_repo import DocumentRepo
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS
from server.agents.document_agent import DocumentAgent  # 导入DocumentAgent

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TextProcessor:
    """
    文本处理器
    """
    def extract_text(self, file_path: str) -> str:
        """
        从文本文件中提取文本
        """
        logger.debug(f"使用TextProcessor提取文本: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        logger.debug(f"TextProcessor提取完成，内容长度: {len(content)}")
        return content

class PDFProcessor:
    """
    PDF处理器
    """
    def extract_text(self, file_path: str) -> str:
        """
        从PDF文件中提取文本
        """
        logger.debug(f"使用PDFProcessor提取文本: {file_path}")
        try:
            import pypdf
            with open(file_path, 'rb') as file:
                pdf_reader = pypdf.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            logger.debug(f"PDFProcessor提取完成，内容长度: {len(text)}")
            return text
        except ImportError:
            logger.error("pypdf未安装，无法解析PDF文件")
            raise
        except Exception as e:
            logger.error(f"PDF处理失败: {str(e)}")
            raise


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
        self.document_agent = DocumentAgent()  # 初始化DocumentAgent
        
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

    def _chunk_by_paragraphs(self, text: str, max_length: int = 600) -> list:
        """
        按段落分块
        """
        logger.debug(f"使用段落分块策略，最大长度: {max_length}")
        
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ""
        
        for i, para in enumerate(paragraphs):
            # 如果单个段落就超过了最大长度，需要进一步分割
            if len(para) > max_length:
                sub_chunks = self._split_long_paragraph(para, max_length)
                for sub_chunk in sub_chunks:
                    if len(current_chunk) + len(sub_chunk) <= max_length:
                        current_chunk += "\n\n" + sub_chunk if current_chunk else sub_chunk
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = sub_chunk
            else:
                # 检查添加当前段落后是否会超过最大长度
                if len(current_chunk) + len(para) <= max_length:
                    current_chunk += "\n\n" + para if current_chunk else para
                else:
                    # 如果当前块不为空，先保存它
                    if current_chunk:
                        chunks.append(current_chunk)
                    # 尝试开始一个新块
                    current_chunk = para
        
        # 添加最后一个块
        if current_chunk:
            chunks.append(current_chunk)
        
        logger.debug(f"段落分块完成，生成 {len(chunks)} 个文本块")
        return chunks

    def _chunk_by_sections(self, text: str, max_length: int = 800) -> list:
        """
        按章节分块
        """
        logger.debug(f"使用章节分块策略，最大长度: {max_length}")
        
        # 简单按标题分块（以"第"字开头或包含"一、二、"等的行）
        import re
        # 匹配标题模式
        title_pattern = r'^(第[一二三四五六七八九十\d]+[章节])|([一二三四五六七八九十\d]、)'
        
        lines = text.split('\n')
        chunks = []
        current_chunk = ""
        current_title = ""
        
        for line in lines:
            if re.match(title_pattern, line.strip()):
                # 遇到新标题，保存当前块
                if current_chunk and current_title:
                    chunks.append(current_title + "\n\n" + current_chunk)
                current_title = line.strip()
                current_chunk = ""
            elif len(current_chunk) + len(line) <= max_length:
                current_chunk += "\n" + line
            else:
                # 当前块已满，保存
                if current_chunk:
                    if current_title:
                        chunks.append(current_title + "\n\n" + current_chunk)
                    else:
                        chunks.append(current_chunk)
                current_chunk = line
        
        # 添加最后一个块
        if current_chunk:
            if current_title:
                chunks.append(current_title + "\n\n" + current_chunk)
            else:
                chunks.append(current_chunk)
        
        logger.debug(f"章节分块完成，生成 {len(chunks)} 个文本块")
        return chunks

    def _split_long_paragraph(self, text: str, max_length: int) -> list:
        """
        分割过长的段落
        """
        logger.debug(f"分割长段落，最大长度: {max_length}")
        
        sentences = text.split('。')  # 以句号为界分割
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence += '。'  # 加回句号
            if len(current_chunk) + len(sentence) <= max_length:
                current_chunk += sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                if len(sentence) > max_length:
                    # 如果单个句子就超过最大长度，按字符硬分割
                    for i in range(0, len(sentence), max_length):
                        chunks.append(sentence[i:i+max_length])
                    current_chunk = ""
                else:
                    current_chunk = sentence
        
        if current_chunk:
            chunks.append(current_chunk)
        
        logger.debug(f"长段落分割完成，生成 {len(chunks)} 个子段落")
        return chunks

    def _chunk_text(self, text: str, doc_analysis: Optional[Dict] = None) -> list:
        """
        将文本分块
        根据文档分析结果调整分块策略
        """
        logger.debug(f"开始文本分块，原始文本长度: {len(text)}")
        
        # 根据文档分析结果确定分块策略
        if doc_analysis:
            strategy = doc_analysis.get('suggested_chunk_strategy', 'general_document')
            logger.debug(f"使用文档分析建议的分块策略: {strategy}")
            
            # 根据文档类型调整分块参数
            if "财务报告" in strategy or "financial" in strategy.lower():
                # 财务报告：按章节或表格分块
                chunks = self._chunk_by_sections(text, max_length=800)
            elif "etf" in strategy.lower() or "基金" in strategy or "fund" in strategy.lower():
                # ETF报告：按基金要素分块
                chunks = self._chunk_by_sections(text, max_length=600)
            elif "新闻" in strategy or "news" in strategy.lower():
                # 新闻文章：按段落分块
                chunks = self._chunk_by_paragraphs(text, max_length=500)
            else:
                # 默认分块策略
                chunks = self._chunk_by_paragraphs(text, max_length=600)
        else:
            # 默认分块策略
            chunks = self._chunk_by_paragraphs(text, max_length=600)
        
        logger.debug(f"文本分块完成，共生成 {len(chunks)} 个块")
        return chunks

    def ingest_document(self, url: str, source: str = "web") -> Dict[str, any]:
        """
        处理文档的主方法
        步骤:
        1. 下载文档内容
        2. 根据URL或内容确定文件扩展名
        3. 获取对应的处理器
        4. 从文档中提取文本
        5. 使用DocumentAgent分析文档
        6. 根据分析结果智能分块
        7. 将文本块向量化并存储
        8. 清理临时文件
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
        
        # === 步骤3: 保存到临时文件 ===
        logger.debug("3️⃣ 保存到临时文件...")
        temp_file_path = self._save_to_temp_file(content, file_extension)
        logger.debug(f"  临时文件路径: {temp_file_path}")
        
        try:
            # === 步骤4: 从文档中提取文本 ===
            logger.debug("4️⃣ 从文档中提取文本...")
            text = processor.extract_text(temp_file_path)
            logger.debug(f"  提取完成，文本长度: {len(text)} 字符")
            
            # === 步骤5: 使用DocumentAgent分析文档 ===
            logger.debug("5️⃣ 使用DocumentAgent分析文档...")
            doc_analysis = self.document_agent.analyze(text)
            logger.debug(f"  文档分析完成，类型: {doc_analysis['document_type']}, 置信度: {doc_analysis['confidence']:.2f}")
            
            # === 步骤6: 根据分析结果进行智能分块 ===
            logger.debug("6️⃣ 根据分析结果进行智能分块...")
            chunks = self._chunk_text(text, doc_analysis)
            logger.debug(f"  分块完成，共 {len(chunks)} 个文本块")
            
            # === 步骤7: 将文本块向量化并存储 ===
            logger.debug("7️⃣ 将文本块向量化并存储...")
            vectors = []
            for i, chunk in enumerate(chunks):
                vector = self.embedder.embed_text(chunk)
                vectors.append(vector)
            
            # 存储结果
            doc_id = self._store_results(chunks, vectors)
            logger.debug(f"  向量化和存储完成，文档ID: {doc_id}")
            
        finally:
            # === 步骤8: 清理临时文件 ===
            logger.debug("8️⃣ 清理临时文件...")
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                logger.debug(f"  临时文件已删除: {temp_file_path}")
        
        logger.info(f"✅ 文档处理完成! ID: {doc_id}")
        logger.info("=" * 60)
        return {"status": "success", "doc_id": doc_id, "chunks_count": len(chunks)}
        
        logger.info(f"✅ 文档处理完成! ID: {doc_id}")
        logger.info("=" * 60)
        return doc_id
    
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

