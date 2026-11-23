import os
from pathlib import Path

# 设置 HuggingFace 国内镜像源，解决下载超时问题
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import re
from dotenv import load_dotenv
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
import PyPDF2
import pdfplumber
import logging

try:
    import fitz  # PyMuPDF
    from rapidocr_onnxruntime import RapidOCR
    HAS_RAPID_OCR = True
    ocr_engine = RapidOCR()
except ImportError:
    HAS_RAPID_OCR = False

# ⚠️ 关闭第三方库霸屏的 INFO 日志，以免 Supabase HttpClient 污染输出
logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)
# 我们自己脚本中的必要业务日志，提升级别到 WARNING 以穿透上面的屏蔽
logger.setLevel(logging.INFO) 
# 给自有 logger 增加单独的 StreamHandler 使之能够在 WARNING 级别下依然打印 INFO 进度
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
# 彻底把 logger 上升为只依赖自有 Handler，不向 Root 传递干扰信息
logger.propagate = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_input_path(path_str: str) -> str:
    """Resolve a user-provided path string to an absolute path.

    Supports being run from either the project root (recommended) or from inside
    the `ai_etf/` package directory.
    """
    raw_path = Path(path_str)
    if raw_path.is_absolute():
        return str(raw_path)

    candidate_from_cwd = (Path.cwd() / raw_path).resolve()
    if candidate_from_cwd.exists():
        return str(candidate_from_cwd)

    candidate_from_root = (PROJECT_ROOT / raw_path).resolve()
    return str(candidate_from_root)

# 1. 加载环境变量 (支持读取项目根目录或脚本当前目录的 .env 文件)
env_path_root = PROJECT_ROOT / ".env"
env_path_local = Path(__file__).resolve().parent / ".env"
load_dotenv(env_path_local if env_path_local.exists() else env_path_root)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("【警告】: 缺少 SUPABASE_URL 或 SUPABASE_KEY。请确保在同级目录下创建了 .env 文件并填入信息！")

# 2. 初始化嵌入模型 (生成向量的核心大脑)
print("正在加载 Embedding 模型（初次加载可能需要一些时间）...")
embedding_model = SentenceTransformer("shibing624/text2vec-base-chinese")

class DocumentProcessor:
    def __init__(self):
        self.documents = {}

    def _extract_pdf_text_layer(self, file_path: str) -> str:
        """Extract embedded text from PDF without OCR.

        This is a Windows-friendly fallback that avoids MinerU OCR weights.
        """
        text_parts: list[str] = []

        # 1) PyPDF2 (fast, best effort)
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_parts.append(page_text)
        except Exception:
            pass

        # 2) pdfplumber (sometimes extracts where PyPDF2 fails)
        if sum(len(p) for p in text_parts) < 200:
            try:
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        if page_text.strip():
                            text_parts.append(page_text)
            except Exception:
                pass

        return "\n".join(text_parts).strip()

    def extract_text(self, pdf_path: str) -> str:
        """
        Extract text from PDF using PyMuPDF and RapidOCR for unstructured/scanned files.
        """
        logger.info(f"正在智能解析文档: {pdf_path}")
        try:
            return self._extract_with_rapidocr(pdf_path)
        except Exception as e:
            logger.warning(f"智能混合提取失败, 降级纯文本: {e}")
            return self._extract_pdf_text_layer(pdf_path)

    def _extract_with_rapidocr(self, pdf_path: str) -> str:
        """
        使用 PyMuPDF 读取文本层，如果某页内容过少（如扫描件图集），则使用 RapidOCR 提取图片文字。
        【阶段二架构】：集成 Pdfplumber 进行多模态并发探测，精准还原金融表格的 Markdown 结构。
        """
        if not HAS_RAPID_OCR:
            logger.warning("未安装 fitz 或 rapidocr_onnxruntime，直接走传统纯文本读取。")
            return self._extract_pdf_text_layer(pdf_path)
            
        doc = fitz.open(pdf_path)
        
        # 🚀 阶段二：开启独立表格结构化辅助引擎 (针对 ETF 招募书中的大量费率、持仓表格)
        try:
            plumber_pdf = pdfplumber.open(pdf_path)
        except Exception:
            plumber_pdf = None

        full_text = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # 1. 优先尝试直接获取文本层 (适合原生PDF文件)
            text = page.get_text()
            
            # --- 🚀 阶段二攻坚：检测并还原 Markdown 表格结构 ---
            table_md = ""
            if plumber_pdf and page_num < len(plumber_pdf.pages):
                try:
                    tables = plumber_pdf.pages[page_num].extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:  # 忽略空表或只有一行的无意义表格
                            continue
                        
                        # 清洗单元格，防止内部换行符破坏 Markdown 格式
                        clean_matrix = []
                        for row in table:
                            clean_row = [str(cell).replace('\n', ' ').replace('|', '\\|').strip() if cell else "-" for cell in row]
                            clean_matrix.append(clean_row)
                        
                        # 将二维数组编译为标准的 Markdown 表格文本
                        headers = clean_matrix[0]
                        md_str = "\n\n| " + " | ".join(headers) + " |\n"
                        md_str += "|" + "|".join(["---"] * len(headers)) + "|\n"
                        for row in clean_matrix[1:]:
                            md_str += "| " + " | ".join(row) + " |\n"
                        
                        table_md += md_str + "\n"
                        logger.info(f"[第{page_num+1}页] 成功捕获并结构化还原一张金融表格。")
                except Exception as e:
                    pass

            # 2. 如果包含很少文字，或者是扫描件图集，我们利用 RapidOCR 接管版面提取
            if len(text.strip()) < 50:
                logger.info(f"[第{page_num+1}页] 判定为非结构化扫描/图片页，启动 RapidOCR 识别...")
                pix = page.get_pixmap(dpi=150) # 高清渲染
                # 转换到 OCR 可用的格式 (BGR or numpy array)
                import numpy as np
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                
                # 如果是 RGBA, 剔除 Alpha通道
                if pix.n == 4:
                    img_data = img_data[:, :, :3]
                    
                # RapidOCR 要求 BGR
                img_bgr = img_data[:, :, ::-1] 
                
                try:
                    ocr_result, _ = ocr_engine(img_bgr)
                    if ocr_result:
                        page_texts = [box_info[1] for box_info in ocr_result]
                        text = "\n".join(page_texts)
                        logger.info(f"[第{page_num+1}页] OCR 成功提取 {len(text)} 字符。")
                except Exception as e:
                    logger.error(f"第 {page_num+1} 页 OCR 解析失败: {e}")
            
            # --- 🚀 混合组装：将表格与文本缝合，防止财务数据丢失 ---
            if table_md:
                text += "\n" + table_md
                
            # 已移除 --- [Page x] --- 的强制追加，避免干扰切片
            full_text.append(text)
            
        doc.close()
        if plumber_pdf:
            plumber_pdf.close()
            
        return "\n\n".join(full_text)

    def process_file_content(self, file_path: str) -> str:
        """根据文件扩展名提取纯文本，支持 .md 和 .pdf"""
        file_path = _resolve_input_path(file_path)
        if not os.path.exists(file_path):
            print(f"文件不存在，跳过: {file_path}")
            return ""

        if file_path.lower().endswith('.md') or file_path.lower().endswith('.txt'):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                print(f"读取 MD 文件失败: {e}")
                return ""
                
        elif file_path.lower().endswith('.docx'):
            try:
                try:
                    import docx
                except ImportError:
                    raise ImportError("python-docx 未安装，请运行: poetry add python-docx")
                    import docx
                    
                doc = docx.Document(file_path)
                full_text = []
                for para in doc.paragraphs:
                    full_text.append(para.text)
                print(f"检测到 Word 文档，成功读取纯文本内容。")
                return "\n".join(full_text)
            except Exception as e:
                print(f"读取 Word 文件失败: {e}")
                return ""
                
        elif file_path.lower().endswith('.pdf'):
            print(f"检测到 PDF 文件，正在使用 RapidOCR 混合图文解析引擎处理...")
            return self.extract_text(file_path)
        else:
            print(f"不支持的文件格式: {file_path}")
            return ""

    def _markdown_semantic_chunking(self, content: str, chunk_size_threshold: int = 500) -> list:
        """
        高级 RAG 技巧：基于 Markdown 标题树的语义切片 (Semantic Chunking)
        将文本按 #, ##, ### 等标题进行逻辑分组，确保同一章节的内容不被强行切断。
        """
        chunks = []
        # 按单个换行符粗略按行读取
        lines = content.split('\n')
        
        current_chunk_text = ""
        current_header = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 检测是否是 Markdown 标题 (例如 "# 基金介绍" 或 "## 1.1 收益率")
            if re.match(r'^#{1,6}\s', line):
                # 遇到新标题时，如果上一个 chunk 已经积累了一些内容，先把它存起来
                if current_chunk_text:
                    # 把所属的标题加上，让向量模型知道这段话是关于什么的
                    context_chunk = f"{current_header}\n{current_chunk_text}" if current_header else current_chunk_text
                    chunks.append(context_chunk)
                    current_chunk_text = ""
                
                # 更新当前正在处理的标题
                current_header = line
            else:
                current_chunk_text += line + "\n"
                
                # 保护机制：如果某个章节的内容实在太长（超出了限制），也要在段落处切一刀
                if len(current_chunk_text) > chunk_size_threshold:
                    context_chunk = f"{current_header}\n{current_chunk_text}" if current_header else current_chunk_text
                    chunks.append(context_chunk.strip())
                    current_chunk_text = ""

        # 收尾：把最后一点没存进去的内容存进去
        if current_chunk_text:
            context_chunk = f"{current_header}\n{current_chunk_text}" if current_header else current_chunk_text
            chunks.append(context_chunk.strip())
            
        return [c for c in chunks if len(c.strip()) > 10]

    def process_files(self, files_dict: dict, chunk_size_threshold: int = 500):
        """处理多个文件，路由分发，统一转化为 Markdown 后切块
        files_dict 的 value 可以是 str(path) 或 tuple(path, doc_type)
        """
        for doc_name, file_entry in files_dict.items():
            # 兼容两种格式：纯路径 或 (路径, 文档类型)
            if isinstance(file_entry, tuple):
                file_path, doc_type = file_entry
            else:
                file_path, doc_type = file_entry, "other"

            resolved_path = _resolve_input_path(file_path)
            if str(Path(file_path)) != resolved_path:
                print(f"正在处理文档: {doc_name} => {file_path} (resolved: {resolved_path}) [doc_type={doc_type}]")
            else:
                print(f"正在处理文档: {doc_name} => {file_path} [doc_type={doc_type}]")
            
            # 这里的 process_file_content 才是真正的 Router（路由器）
            content = self.process_file_content(resolved_path)
            
            if not content:
                print(f"【跳过】: 无法从 {file_path} 提取内容")
                continue
            
            # --- 🚀 匹配项目参报书核心创新点一与研究内容(2)：智能数据清洗与结构重建 ---
            
            # 1. 精准移除“孤立页码”及页脚碎片 (如只有 197, 198 的行，消除低质量语料干扰)
            content = re.sub(r'^\s*\d+\s*$', '', content, flags=re.MULTILINE)
            
            # 2. 伪造/重建 Markdown 语义树：由于 OCR 破坏了原生排版，我们利用正则将“第一章”等恢复为 Markdown 标题
            # 【修复】：移除了将 \d.\d (小数) 当作标题的伪造逻辑，这会摧毁所有的金融表格行并导致后续大面积文本被错误挂在假标题下！
            content = re.sub(r'^\s*(第[一二三四五六七八九十百零0-9]+[章节篇部分]\s+[\u4e00-\u9fa5]+.*)$', r'# \1', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*([一二三四五六七八九十]+、\s*[\u4e00-\u9fa5]+.*)$', r'## \1', content, flags=re.MULTILINE)
            content = re.sub(r'^\s*(（[一二三四五六七八九十]+）\s*[\u4e00-\u9fa5]+.*)$', r'### \1', content, flags=re.MULTILINE)
            
            # 为了防止当前 PDF 提取没有 Markdown 标题，我们兼容一下老版本的清理逻辑
            content = re.sub(r'(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])', '', content)
            content = re.sub(r'[ \t]+', ' ', content)
            content = re.sub(r'\n\s*\n', '\n', content)
            
            # --- 核心大换血：调用语义切片器 ---
            chunks = self._markdown_semantic_chunking(content, chunk_size_threshold)

            # 封装并存储
            doc_chunks = []
            for i, chunk in enumerate(chunks):
                doc_chunks.append({
                    "content": chunk,
                    "doc_name": doc_name,
                    "doc_type": doc_type,
                    "embedding": None
                })
            
            self.documents[doc_name] = doc_chunks
            print(f" --- [{doc_name}] 成功分割成 {len(chunks)} 个文本块！")

    def generate_embeddings(self):
        """调用大模型，将其转化为向量"""
        print("\n开始生成文本向量（Embedding计算中，请耐心等待...）")
        all_chunks = []
        for doc_name, chunks in self.documents.items():
            all_chunks.extend(chunks)
        
        if not all_chunks:
            print("没有提取到任何文本块，终止向量化流程。")
            return

        # 提取出所有的纯文本列，传入模型
        contents = [chunk["content"] for chunk in all_chunks]
        embeddings = embedding_model.encode(contents, normalize_embeddings=True)
        
        # 将生成的向量 [0.03, -0.42...] 赋值回家
        idx = 0
        for doc_name, chunks in self.documents.items():
            for chunk in chunks:
                chunk["embedding"] = embeddings[idx].tolist()
                idx += 1
        print(f"成功为 {idx} 个文本块生成了嵌入向量！")


def upload_to_supabase(processor: DocumentProcessor):
    """把切好的数据组装推送到远程数据库 (完整生命周期版)"""
    if not processor.documents:
        print("\n没有可上传的数据，跳过 Supabase 入库流程。")
        return

    if not url or not key:
        print("\n取消上传: 环境中未配置 Supabase 凭证。")
        return
        
    try:
        supabase: Client = create_client(url, key)
        print("\n成功连接到 Supabase 服务器！准备走完整个知识库入库流程...")
    except Exception as e:
        print(f"\n初始化 Supabase 客户端失败: {e}")
        return

    # 从你的截图中提取出的那个测试用户的 UUID
    USER_ID = "a6ee55ff-b59c-4c2b-bcdd-2519e7072aa1"

    uploaded_docs = 0
    uploaded_chunks = 0
        
    for doc_name, chunks in processor.documents.items():
        print(f"\n开始上传资料: 【{doc_name}】")
        try:
            if not chunks:
                print(f"  -> 【{doc_name}】无切片数据，跳过")
                continue

            # 步骤 1：在 files 表中伪造一条原始文件记录
            file_res = supabase.table("files").insert({
                "user_id": USER_ID,
                "name": f"{doc_name}.pdf",
                "type": "file"
            }).execute()
            file_id = file_res.data[0]["id"]
            
            # 步骤 2：在 documents 表中登记为待处理文档
            doc_res = supabase.table("documents").insert({
                "file_id": file_id,
                "user_id": USER_ID,
                "status": "ready",
                "title": doc_name
            }).execute()
            document_id = doc_res.data[0]["id"]
            
            # 步骤 3：把对应的 chunks 绑定到这个 document_id 写入
            upload_batch = []
            for index, chunk in enumerate(chunks):
                if chunk["embedding"]:
                    upload_batch.append({
                        "document_id": document_id,
                        "chunk_index": index,
                        "content": chunk["content"],
                        "embedding": chunk["embedding"],
                        "document_type": chunk.get("doc_type", "other"),
                    })

            if not upload_batch:
                print(f"  -> 【{doc_name}】没有可写入的 embedding 切片，跳过")
                continue
            
            # 分批写入 chunks 表
            batch_size = 50
            total = len(upload_batch)
            for i in range(0, total, batch_size):
                batch = upload_batch[i:i+batch_size]
                supabase.table("document_chunks").insert(batch).execute()
                print(f"  -> 【{doc_name}】 切块写入进度: {min(i+batch_size, total)} / {total}")

            uploaded_docs += 1
            uploaded_chunks += total
                
        except Exception as e:
            print(f"❌ 上传 【{doc_name}】 时出错: {e}")
            
    if uploaded_docs:
        print(f"\n✅ 入库完成：文档 {uploaded_docs} 篇，切片 {uploaded_chunks} 条。")
    else:
        print("\n⚠️ 未写入任何数据（可能所有文档都解析失败或未生成 embedding）。")

if __name__ == "__main__":
    # 配置要处理的文件字典
    # 根据你的说明，文件移动到了 etf-knowledge 文件夹中
    # 假设你在 ai-etf 根目录下运行代码 (python ai_etf/data_pipeline.py)
    # 如果运行报错找不到该文件，可以改为绝对路径或者 "../etf-knowledge/..."
    target_files = {
        # "华泰博瑞中证红利低波ETF招募书": ("etf-knowledge/huataiborui.pdf", "prospectus"),
        # "南方标普中国A股大盘红利低波50ETF招募书": ("etf-knowledge/nanfangbiaopu.pdf", "prospectus"),
        # "ETF大师投资策略-构建投资组合的最佳实践": ("etf-knowledge/ETF Master Investment Strategies.pdf", "other"),
        # "ETF新手快速入门": ("etf-knowledge/ETF新手快速入门.md", "guide"),
        # "ETF基础知识点": ("etf-knowledge/etf_basic_knowledge.md", "guide"),
        # "股息低波动策略_2026": ("etf-knowledge/dividend_low_volatility_strategy_2026.md", "strategy"),
        # "QDII ETF与跨境投资": ("etf-knowledge/etf_qdii_cross_border.md", "guide"),
        # "ETF税收规则详解": ("etf-knowledge/etf_tax_rules.md", "guide"),
        # "ETF交易规则详解": ("etf-knowledge/etf_trading_rules.md", "guide"),
        # "ETF与其他基金类型对比": ("etf-knowledge/etf_vs_other_funds.md", "guide"),
        "恒生科技指数与ETF投资指南": ("etf-knowledge/hang_seng_tech_etf.md", "guide"),
    }
    
    # 实例化我们的工厂
    pipeline = DocumentProcessor()
    
    # 1. 解析纯文本并切块
    pipeline.process_files(target_files)
    
    # 2. 调用大模型计算向量
    pipeline.generate_embeddings()
    
    # 3. 将数据推送到 Supabase
    upload_to_supabase(pipeline)