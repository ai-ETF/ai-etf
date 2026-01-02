import uuid
import requests
import logging
import tempfile
import os
from pathlib import Path
from server.rag.chunker import split_text
from server.rag.embedder import Embedder
from server.storage.document_repo import DocumentRepo
from server.storage.embedding_repo import EmbeddingRepo
from server.config.settings import SETTINGS

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
        
        # 创建文档存储目录
        self.doc_dir = Path("docs")
        self.doc_dir.mkdir(exist_ok=True)
        
        logger.debug(f"文档服务初始化完成，嵌入维度: {SETTINGS.EMBED_DIM}, 文档目录: {self.doc_dir}")

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

        # 获取原始内容
        content = res.content
        ct = res.headers.get("content-type", "")
        logger.debug(f"文档内容类型: {ct}")
        
        # 根据文件扩展名或内容类型判断文件类型
        file_extension = self._get_file_extension(url, ct)
        logger.debug(f"检测到文件扩展名: {file_extension}")
        
        # 所有文档都先保存到docs目录
        doc_filename = f"etf_doc_{uuid.uuid4()}{file_extension}"
        doc_file_path = self.doc_dir / doc_filename
        
        with open(doc_file_path, 'wb') as doc_file:
            doc_file.write(content)
            logger.debug(f"文档已保存到: {doc_file_path}")

        text = None
        # 根据内容类型决定如何处理文档
        if self._is_text_type(file_extension, ct):
            # 对于文本类型文件，直接使用文本内容
            text = res.text
            logger.debug(f"检测到文本内容，长度: {len(text)} 字符")
        else:
            # 对于非文本文件（如PDF），从文档文件中提取文本
            # 尝试从文件中提取文本内容
            text = self._extract_text_from_file(str(doc_file_path), file_extension)
            if not text:
                logger.warning(f"无法从二进制文件中提取文本内容，使用占位符")
                text = f"[binary document downloaded from {url}; size={len(content)} bytes; saved at: {doc_file_path}]"
            else:
                logger.debug(f"从二进制文件中成功提取文本内容，长度: {len(text)} 字符")

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
        
        # 开始标记和文本块预览
        logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        logger.debug("文本块内容预览 (前5个，限制200字符):")
        for i, c in enumerate(chunks[:5]):
            preview = c[:200] + ("..." if len(c) > 200 else "")
            logger.debug(f"块 {i+1}/{len(chunks)} 预览: {preview}")
            logger.debug(f"块 {i+1} 完整长度: {len(c)} 字符")
        logger.debug("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")

        items = []
        vector_generation_start = False
        
        for i, c in enumerate(chunks):
            # 只打印前10个文本块的详细处理信息
            if i < 10:
                if not vector_generation_start:
                    logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    logger.debug("开始生成嵌入向量 (仅显示前10个块的详细信息):")
                    vector_generation_start = True
                
                logger.debug(f"处理块 {i+1}/{len(chunks)} - 长度: {len(c)} 字符")
                
                # 为每个文本块生成嵌入向量
                vector = self.embedder.embed_text(c)
                
                # 打印前5个向量的预览
                if i < 5:
                    # 只显示前10个值
                    vector_preview = vector[:10]
                    logger.debug(f"块 {i+1} 向量预览 (前10个值): {vector_preview}")
                    logger.debug(f"块 {i+1} 完整向量长度: {len(vector)} 维度")
                
                logger.debug("-" * 50)
            elif i == 10:
                logger.debug("... 更多文本块正在处理中，为保持日志清晰，省略后续详细日志 ...")
                logger.debug("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
            
            items.append({"chunk_id": f"{doc_id}.{i}", "text": c, "vector": vector})

        # 如果处理了少于10个块，添加结束标记
        if len(chunks) <= 10 and vector_generation_start:
            logger.debug("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")

        # 持久化存储嵌入向量
        logger.debug(f"开始存储 {len(items)} 个嵌入向量")
        
        # 在存储嵌入向量时添加更清晰的日志
        logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        self.emb_repo.insert_many(doc_id, items)
        logger.debug("嵌入向量存储完成")
        logger.debug("<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")

        logger.debug(f"文档处理完成，返回文档ID: {doc_id}")
        
        # 清理文档文件
        try:
            os.unlink(doc_file_path)
            logger.debug(f"文档文件已清理: {doc_file_path}")
        except OSError as e:
            logger.error(f"删除文档文件失败 {doc_file_path}: {e}")
        
        return doc_id

    def _is_text_type(self, file_extension: str, content_type: str) -> bool:
        """
        判断是否为文本类型文件
        """
        # 检查文件扩展名
        text_extensions = ['.txt', '.md', '.html', '.htm', '.py', '.js', '.ts', '.json', '.xml', '.csv']
        if file_extension.lower() in text_extensions:
            return True
            
        # 检查内容类型
        if "text" in content_type:
            return True
            
        return False

    def _get_file_extension(self, url: str, content_type: str) -> str:
        """
        根据URL或内容类型获取文件扩展名
        """
        # 首先尝试从URL获取扩展名
        path = Path(url).suffix.lower()
        if path:
            return path
            
        # 如果URL没有扩展名，尝试从content-type推断
        content_type_map = {
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
            'application/vnd.ms-excel': '.xls',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
            'text/csv': '.csv',
            'text/plain': '.txt',
            'text/html': '.html',
            'application/json': '.json',
            'application/xml': '.xml',
            'text/xml': '.xml',
        }
        
        return content_type_map.get(content_type, '.dat')  # 默认扩展名

    def _extract_text_from_file(self, file_path: str, file_extension: str) -> str:
        """
        从文件中提取文本内容
        """
        logger.debug(f"尝试从文件中提取文本内容: {file_path}, 扩展名: {file_extension}")
        
        # 如果是PDF文件，使用pypdf提取文本
        if file_extension.lower() == '.pdf':
            try:
                import pypdf
                text = ""
                with open(file_path, 'rb') as file:
                    pdf_reader = pypdf.PdfReader(file)
                    for page in pdf_reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                logger.debug(f"PDF文件文本提取完成，提取字符数: {len(text)}")
                return text
            except ImportError:
                logger.error("pypdf库未安装，无法处理PDF文件")
                return ""
            except Exception as e:
                logger.error(f"PDF文件处理失败: {e}")
                return ""
        
        # 如果是其他二进制文件，暂时返回空字符串
        # 可以在这里添加对其他文件类型的处理
        logger.debug(f"不支持的文件类型，无法提取文本: {file_extension}")
        return ""