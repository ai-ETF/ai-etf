from typing import List, Dict, Tuple
import PyPDF2
import pdfplumber
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import pysqlite3

import os
import json
from typing import List, Dict, Optional
from dotenv import load_dotenv

import sys

sys.modules['sqlite3'] = pysqlite3
# 加载环境变量
load_dotenv()

# 导入扣子官方SDK
from cozepy import COZE_CN_BASE_URL, ChatEventType, Coze, Message, TokenAuth
# 初始化模型
embedding_model = SentenceTransformer("shibing624/text2vec-base-chinese")

class MultiPDFProcessor:
    def __init__(self):
        # 创建了一个空字典 documents 来存储所有处理后的文档数据
        self.documents = {}  # 存储不同文档的块和元数据
    
    def process_multiple_pdfs(self, pdf_files: Dict[str, str]) -> None:
        """
        处理多个PDF文件，并为每个文档添加来源标识
        
        Args:
            pdf_files: 字典，格式为 {文档标识: 文件路径}
                      例如: {"南方基金": "south_fund.pdf", "标普基金": "sp_fund.pdf"}
        """
        # 遍历所有PDF文件
        for doc_name, pdf_path in pdf_files.items():
            print(f"正在处理文档: {doc_name} - {pdf_path}")
            
            # 分块处理
            chunks = self.split_pdf_into_chunks(pdf_path)
            
            # 为每个块添加文档标识
            doc_chunks = []
            for i, chunk in enumerate(chunks):
                doc_chunks.append({
                    "content": chunk,        # 文本内容
                    "doc_name": doc_name,    # 文档标识
                    "chunk_id": f"{doc_name}_{i}",   # 唯一块ID
                    "embedding": None  # 预留嵌入向量字段
                })
            
            self.documents[doc_name] = doc_chunks   # 存储结果
            print(f"文档 {doc_name} 分割成 {len(chunks)} 个块")
    
    def extract_text_from_pdf(self, pdf_file: str) -> str:
        """从PDF提取文本（与之前相同）"""
        text = ""
        # 第一层：PyPDF2 尝试
        try:
            # 以二进制模式('rb')打开文件
            with open(pdf_file, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                # 逐页遍历并提取文本
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        # 添加换行符 \n 保持页面分隔
                        text += page_text + "\n"
        except Exception as e:
            print(f"PyPDF2提取失败: {e}, 尝试使用pdfplumber...")
            try:
                with pdfplumber.open(pdf_file) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
            except Exception as e2:
                print(f"pdfplumber提取也失败: {e2}")
                return ""
        return text
    
    def split_pdf_into_chunks(self, pdf_file: str, chunk_size_threshold: int = 300) -> List[str]:
        """PDF分块（与之前相同）
            pdf_file: PDF文件路径
            chunk_size_threshold: 块大小阈值，默认300字符
        """
        # 调用之前的 extract_text_from_pdf 方法提取原始文本
        content = self.extract_text_from_pdf(pdf_file)
        if not content:
            print("警告: 无法从PDF中提取文本内容")
            return []
        
        # 文本清洗：' '.join(content.split()) 去除多余空白字符
        # 段落分割：按换行符 \n 分割成段落，并去除空段落
        content = ' '.join(content.split())
        paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
        
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            # 将小段落合并，直到接近阈值
            if len(current_chunk) + len(paragraph) <= chunk_size_threshold:
                if current_chunk:
                    # 使用双换行符 \n\n 保持段落间的视觉分隔
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = paragraph
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # 备选方案：句子分割
        if len(chunks) == 0 or (len(chunks) == 1 and len(chunks[0]) > 1000):
        # 零分块：分段方法完全失败，没有产生任何分块
        # 单一超大分块：只产生了一个分块且长度超过1000字符，说明分段方法效果不佳        
            print("使用句子分割作为备选方案...")
            import re
            # 使用正则表达式按中英文标点分割句子
            sentences = re.split(r'[。！？!?]', content)
            # 滤掉过短的句子（少于10字符），避免无意义片段
            sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
            
            chunks = []
            current_chunk = ""
            # 将短句子合并到接近阈值大小
            for sentence in sentences:
                if len(current_chunk) + len(sentence) <= chunk_size_threshold:
                    if current_chunk:
                        # 使用句号连接句子，保持语法正确性
                        current_chunk += "。" + sentence
                    else:
                        current_chunk = sentence
                else:
                    if current_chunk:
                        # 确保每个块以句号结束
                        chunks.append(current_chunk + "。")
                    current_chunk = sentence
            
            if current_chunk:
                chunks.append(current_chunk + "。")
        
        return chunks
    
    # 为所有PDF文档的所有文本块生成嵌入向量（embedding），将文本转换为数值表示。
    def generate_embeddings_for_all(self) -> None:
        """为所有文档的所有块生成嵌入向量"""
        all_chunks = []
        for doc_name, chunks in self.documents.items():
            all_chunks.extend(chunks)
        
        # 批量生成嵌入向量（效率更高）//收集所有文本块后一次性编码，比逐个编码效率高很多
        
        # 只提取文本内容 chunk["content"] 进行编码
        contents = [chunk["content"] for chunk in all_chunks]
        # normalize_embeddings=True 确保向量在同一尺度，便于相似度计算
        embeddings = embedding_model.encode(contents, normalize_embeddings=True)
        
        # 分配嵌入向量
        idx = 0
        # 保持原有的文档-块结构
        for doc_name, chunks in self.documents.items():
            for chunk in chunks:
                # tolist() 将numpy数组转换为Python列表，便于序列化存储
                chunk["embedding"] = embeddings[idx].tolist()
                idx += 1
        
        print(f"已为 {idx} 个文本块生成嵌入向量")
    
    # 基于语义相似度搜索与查询相关的文本块，支持跨文档检索。
    def search_related_chunks(self, query: str, top_k: int = 10) -> List[Dict]:
        # 基于语义相似度搜索与查询相关的文本块，支持跨文档检索。
        
        """
        搜索与查询相关的文本块，按相关性排序
        
        Args:
            query: 查询文本
            top_k: 返回最相关的前k个结果
            
        Returns:
            相关文本块列表，包含内容和来源信息
        """

        # 生成查询的嵌入向量
        query_embedding = embedding_model.encode([query], normalize_embeddings=True)[0]
        
        # 收集所有块和它们的嵌入向量
        all_chunks = []
        all_embeddings = []
        # 将查询文本转换为相同的嵌入空间
        for doc_name, chunks in self.documents.items():
            for chunk in chunks:
                # 过滤掉未生成嵌入向量的块
                if chunk["embedding"] is not None:
                    all_chunks.append(chunk)
                    all_embeddings.append(chunk["embedding"])
        
        if not all_embeddings:
            return []
        
        # 计算相似度
        similarities = cosine_similarity([query_embedding], all_embeddings)[0]
        
        # 按相似度排序
        scored_chunks = list(zip(all_chunks, similarities))
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        
        # 返回前k个结果
        return [chunk for chunk, score in scored_chunks[:top_k]]
    
    def search_by_document(self, query: str, top_k_per_doc: int = 5) -> Dict[str, List[Dict]]:
        """
        按文档分别搜索相关块，确保每个文档都有代表性内容
        
        Args:
            query: 查询文本
            top_k_per_doc: 每个文档返回的最相关块数量
            
        Returns:
            按文档分组的相关块字典
        """
        query_embedding = embedding_model.encode([query], normalize_embeddings=True)[0]
        
        results_by_doc = {}
        
        for doc_name, chunks in self.documents.items():
            # 对每个文档独立进行搜索和排序
            valid_chunks = [chunk for chunk in chunks if chunk["embedding"] is not None]
            # 过滤出有嵌入向量的块
            if not valid_chunks:
                continue
            
            # 计算相似度
            embeddings = [chunk["embedding"] for chunk in valid_chunks]
            similarities = cosine_similarity([query_embedding], embeddings)[0]
            
            # 排序并取前k个
            scored_chunks = list(zip(valid_chunks, similarities))
            scored_chunks.sort(key=lambda x: x[1], reverse=True)
            
            results_by_doc[doc_name] = [chunk for chunk, score in scored_chunks[:top_k_per_doc]]
        
        return results_by_doc

# 使用示例
def compare_etf_funds():
    """对比两只ETF基金的示例"""
    
    # 初始化处理器
    processor = MultiPDFProcessor()
    
    # 定义要处理的PDF文件
    pdf_files = {
        "南方基金": "515450_20250417_BW9G.pdf",
        "中泰柏瑞基金": "512890_20250726_9V72.pdf"
    }
    
    # 处理多个PDF
    processor.process_multiple_pdfs(pdf_files)
    
    # 生成嵌入向量
    processor.generate_embeddings_for_all()
    
    # 对比查询
    query = "对比 A 和 B 两只的基金收益分配原则"
    
    print(f"\n查询: {query}")
    print("=" * 50)
    
    # 方法1：按文档分别搜索（推荐用于对比分析）
    results_by_doc = processor.search_by_document(query, top_k_per_doc=5)
    
    # 构建对比分析用的提示词
    comparison_prompt = build_comparison_prompt(query, results_by_doc)
    
    print("对比分析提示词:")
    print(comparison_prompt)
    print("=" * 50)
    
    #显示每个文档的相关内容，便于验证搜索效果
    for doc_name, chunks in results_by_doc.items():
        print(f"\n{doc_name} 相关片段:")
        for i, chunk in enumerate(chunks):
            print(f"[{i}] {chunk['content'][:1000]}...")  # 显示前200字符
    
    return comparison_prompt, results_by_doc

def build_comparison_prompt(query: str, results_by_doc: Dict[str, List[Dict]]) -> str:
    """
    构建对比分析用的提示词
    
    Args:
        query: 原始查询
        results_by_doc: 按文档分组的相关块
        
    Returns:
        格式化的提示词
    """
    prompt = f"用户问题: {query}\n\n"
    prompt += "请基于以下两个基金的文档片段，对比分析它们的相关信息：\n\n"
    
    for doc_name, chunks in results_by_doc.items():
        # 清晰分隔不同文档的来源
        prompt += f"=== {doc_name} 相关信息 ===\n"
        for i, chunk in enumerate(chunks):
            # 为每个片段编号，便于引用
            prompt += f"片段 {i+1}: {chunk['content']}\n"
        prompt += "\n"
    
    # prompt += "请从以下几个方面进行对比分析：\n"
    # prompt += "1. 行业集中度差异\n"
    # prompt += "2. 主要持仓行业分布\n" 
    # prompt += "3. 风险分散程度\n"
    # prompt += "4. 投资策略特点\n\n"
    prompt += "请基于提供的文档内容进行客观分析，不要编造信息。"
    
    return prompt

# # 更高级的对比分析函数
# def advanced_fund_comparison(processor: MultiPDFProcessor, 
#                            fund_a: str, fund_b: str, 
#                            comparison_aspects: List[str] = None) -> str:
#     """
#     高级基金对比分析
    
#     Args:
#         processor: 多PDF处理器
#         fund_a: 基金A的名称
#         fund_b: 基金B的名称
#         comparison_aspects: 对比维度列表
        
#     Returns:
#         对比分析提示词
#     """
#     if comparison_aspects is None:
#         comparison_aspects = [
#             "前十大重仓股", "行业分布", "投资策略", "风险特征", "业绩表现"
#         ]
    
#     # 为每个对比维度搜索相关内容
#     all_results = {}
    
#     # 为每个分析维度独立构建查询
#     # 每个维度在每个基金中搜索3个最相关片段
#     # 按维度组织搜索结果，便于后续分析
#     for aspect in comparison_aspects:
#         query = f"{fund_a} 和 {fund_b} 的 {aspect}"
#         results = processor.search_by_document(query, top_k_per_doc=3)
#         all_results[aspect] = results
    
#     # 构建详细的对比提示词
#     prompt = f"请对比分析 {fund_a} 和 {fund_b} 两只基金：\n\n"
    
#     for aspect, results in all_results.items():
#         prompt += f"【{aspect}对比】\n"
        
#         for fund_name in [fund_a, fund_b]:
#             if fund_name in results and results[fund_name]:
#                 prompt += f"{fund_name}:\n"
#                 for chunk in results[fund_name]:
#                     prompt += f"- {chunk['content'][:150]}...\n"
#             else:
#                 prompt += f"{fund_name}: 相关信息不足\n"
        
#         prompt += "\n"
    
#     prompt += "请基于以上信息进行全面的对比分析，总结两者的异同点。"
    
#     return prompt
def generate(prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
    """
    使用扣子平台官方SDK生成回答的增强函数
    
    支持多种使用场景：
    1. 直接传入完整提示词
    2. 传入系统提示词和用户问题
    3. 支持对比分析等复杂场景
    
    Args:
        prompt: 完整的提示词内容，或用户问题
        system_prompt: 可选的系统提示词，用于定义角色和任务
        **kwargs: 其他参数，如 chunks, comparison_data 等
        
    Returns:
        LLM生成的回答内容
    """
    
    print(f"最终提示词:\n{prompt}\n{'-'*50}\n")

    # API配置
    COZE_API_TOKEN = "pat_uHBs4satkGsxDZQ1dhAg66mW5IX07HtqAPCbxl0q3bsMLPd50aT5AhLL11Dpw35U"
    COZE_BOT_ID = "7547655862975053865"
    
    # 初始化扣子客户端
    coze = Coze(
        auth=TokenAuth(token=COZE_API_TOKEN),
        base_url=COZE_CN_BASE_URL
    )
    
    # 用户ID
    user_id = "rag_learning_user_001"
    
    # 收集完整响应内容
    full_response = ""
    
    try:
        # 使用流式聊天接口
        stream = coze.chat.stream(
            bot_id=COZE_BOT_ID,
            user_id=user_id,
            additional_messages=[
                Message.build_user_question_text(prompt),
            ],
            parameters=kwargs.get('parameters', {}),
        )
        
        print("logid:", stream.response.logid)
        print("开始生成回答...")
        
        # 处理流式响应事件
        for event in stream:
            if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
                # 收集内容增量
                if event.message.content:
                    full_response += event.message.content
                    print(event.message.content, end="", flush=True)
            
            elif event.event == ChatEventType.CONVERSATION_CHAT_COMPLETED:
                print("\n----- 对话完成 -----")
                if hasattr(event.chat, 'usage') and event.chat.usage:
                    print(f"token用量: {event.chat.usage.token_count}")
                break
            
            elif event.event == ChatEventType.CONVERSATION_CHAT_FAILED:
                print("\n----- 对话失败 -----")
                if hasattr(event.chat, 'last_error') and event.chat.last_error:
                    return f"聊天失败: {event.chat.last_error}"
                else:
                    return "聊天失败，未知错误"
        
        return full_response
        
    except Exception as e:
        error_msg = f"请求过程中出现错误: {str(e)}"
        print(error_msg)
        return error_msg    

if __name__ == "__main__":
    # 运行对比分析
    comparison_prompt, results = compare_etf_funds()
    
    # 这里可以将 comparison_prompt 传递给您的 generate 函数
    
    answer = generate(comparison_prompt, system_prompt="你是一个资深基金分析师，请分析以下内容：")  # 注意：这里不需要单独的chunks参数

    print(answer)