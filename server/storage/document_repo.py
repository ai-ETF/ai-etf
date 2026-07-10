import json
from typing import Optional, List, Dict
import logging
from datetime import datetime
from server.storage.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class DocumentRepo:
    def __init__(self, db_path: Optional[str] = None):
        logger.debug(f"初始化DocumentRepo")
        self.supabase = get_supabase()
        
        if not self.supabase:
            error_msg = "Supabase客户端初始化失败，请检查环境变量SUPABASE_URL和SUPABASE_SERVICE_ROLE_KEY是否已设置"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
            
        logger.info("使用Supabase作为文档存储")

    def save_document_chunks(self, doc_id: str, chunks: List[Dict]):
        """
        保存文档分块到 document_chunks 表
        chunks: 已经过滤掉元数据的纯文本块列表
        """
        logger.debug(f"保存文档分块，文档ID: {doc_id}, 块数: {len(chunks)}")
        
        try:
            # 准备批量数据
            chunks_data = []
            for i, chunk in enumerate(chunks):
                # 确保每个分块都有必需的信息
                chunk_data = {
                    "document_id": doc_id,
                    "document_name": chunk.get("document_name", f"chunk_{doc_id}_{i}"),
                    "document_type": chunk.get("document_type", "text_chunk"),
                    "chunk_index": chunk.get("chunk_index", i),
                    "content": chunk.get("text", ""),
                    "embedding": self._format_vector_for_db(chunk.get("embedding", [])),
                    "page_number": chunk.get("page_number", 1),
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }
                
                # 跳过空内容或无效的分块
                if not self._is_valid_chunk(chunk_data):
                    logger.debug(f"跳过无效分块: 索引={i}, 内容长度={len(chunk_data['content'])}")
                    continue
                    
                chunks_data.append(chunk_data)
            
            # 批量插入
            if chunks_data:
                # 首先删除该文档的所有旧分块（避免重复）
                self._delete_document_chunks(doc_id)
                
                # 批量插入新分块
                response = self.supabase.table("document_chunks").insert(chunks_data).execute()
                logger.debug(f"成功插入 {len(chunks_data)} 个文档块")
                return len(chunks_data)
            else:
                logger.warning("没有有效的文档分块需要保存")
                return 0
                
        except Exception as e:
            error_msg = f"Supabase保存文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def save_single_chunk(self, doc_id: str, chunk_data: Dict):
        """保存单个文档分块"""
        try:
            # 确保有必需的字段
            chunk_index = chunk_data.get("chunk_index", 0)
            content = chunk_data.get("text", "")
            
            logger.debug(f"保存单个文档分块，文档ID: {doc_id}, 块索引: {chunk_index}, 内容长度: {len(content)}")
            
            # 跳过空内容
            if not content or len(content.strip()) == 0:
                logger.warning("内容为空，跳过保存")
                return None
            
            # 准备分块数据
            chunk_entry = {
                "document_id": doc_id,
                "document_name": chunk_data.get("document_name", f"chunk_{doc_id}_{chunk_index}"),
                "document_type": chunk_data.get("document_type", "text_chunk"),
                "chunk_index": chunk_index,
                "content": content,
                "embedding": self._format_vector_for_db(chunk_data.get("embedding", [])),
                "page_number": chunk_data.get("page_number", 1),
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            
            # 插入分块
            response = self.supabase.table("document_chunks").insert(chunk_entry).execute()
            
            if response.data and len(response.data) > 0:
                chunk_id = response.data[0]["id"]
                logger.debug(f"文档分块保存成功，chunk_id: {chunk_id}")
                return chunk_id
            else:
                logger.error(f"保存文档分块失败，无返回数据")
                return None
                
        except Exception as e:
            error_msg = f"Supabase保存单个文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_document_chunks(self, doc_id: str):
        """获取文档的所有分块"""
        logger.debug(f"获取文档分块，文档ID: {doc_id}")
        
        try:
            response = self.supabase.table("document_chunks").select("*").eq("document_id", doc_id).order("chunk_index").execute()
            
            chunks = []
            if response.data:
                for row in response.data:
                    chunk = {
                        "id": row["id"],
                        "chunk_index": row["chunk_index"],
                        "content": row["content"],
                        "page_number": row.get("page_number", 1),
                        "document_name": row.get("document_name", ""),
                        "document_type": row.get("document_type", ""),
                        "embedding": self._parse_vector_from_db(row.get("embedding")),
                        "created_at": row.get("created_at", "")
                    }
                    chunks.append(chunk)
            
            logger.debug(f"获取到 {len(chunks)} 个文档分块")
            return chunks
            
        except Exception as e:
            error_msg = f"Supabase获取文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_chunk_by_id(self, chunk_id: str):
        """根据ID获取单个分块"""
        logger.debug(f"获取分块，ID: {chunk_id}")
        
        try:
            response = self.supabase.table("document_chunks").select("*").eq("id", chunk_id).execute()
            
            if response.data and len(response.data) > 0:
                row = response.data[0]
                chunk = {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "page_number": row.get("page_number", 1),
                    "document_name": row.get("document_name", ""),
                    "document_type": row.get("document_type", ""),
                    "embedding": self._parse_vector_from_db(row.get("embedding")),
                    "created_at": row.get("created_at", "")
                }
                return chunk
            else:
                logger.debug(f"分块 {chunk_id} 不存在")
                return None
                
        except Exception as e:
            error_msg = f"Supabase获取分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def delete_document_chunks(self, doc_id: str):
        """删除文档的所有分块"""
        logger.debug(f"删除文档分块，文档ID: {doc_id}")
        
        try:
            response = self.supabase.table("document_chunks").delete().eq("document_id", doc_id).execute()
            
            deleted_count = len(response.data) if response.data else 0
            logger.debug(f"文档 {doc_id} 的 {deleted_count} 个分块删除成功")
            return deleted_count
                
        except Exception as e:
            error_msg = f"Supabase删除文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def search_chunks_by_content(self, keyword: str, limit: int = 10):
        """根据内容关键词搜索分块"""
        logger.debug(f"根据内容搜索分块，关键词: {keyword}")
        
        try:
            # 使用模糊搜索
            response = self.supabase.table("document_chunks").select("*").ilike("content", f"%{keyword}%").limit(limit).execute()
            
            chunks = []
            if response.data:
                for row in response.data:
                    chunk = {
                        "id": row["id"],
                        "document_id": row["document_id"],
                        "chunk_index": row["chunk_index"],
                        "content": row["content"],
                        "page_number": row.get("page_number", 1),
                        "document_name": row.get("document_name", ""),
                        "document_type": row.get("document_type", "")
                    }
                    chunks.append(chunk)
            
            logger.debug(f"找到 {len(chunks)} 个包含关键词 '{keyword}' 的分块")
            return chunks
            
        except Exception as e:
            error_msg = f"Supabase根据内容搜索分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_all_documents(self):
        """获取所有文档的ID列表"""
        logger.debug("获取所有文档ID列表")
        
        try:
            # 使用DISTINCT获取所有唯一的document_id
            response = self.supabase.table("document_chunks").select("document_id").execute()
            
            documents = []
            if response.data:
                # 去重
                seen = set()
                for row in response.data:
                    doc_id = row["document_id"]
                    if doc_id not in seen:
                        seen.add(doc_id)
                        documents.append(doc_id)
            
            logger.debug(f"找到 {len(documents)} 个文档")
            return documents
            
        except Exception as e:
            error_msg = f"Supabase获取所有文档失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_document_stats(self, doc_id: str):
        """获取文档的统计信息"""
        logger.debug(f"获取文档统计信息，文档ID: {doc_id}")
        
        try:
            # 获取文档的所有分块
            chunks = self.get_document_chunks(doc_id)
            
            if not chunks:
                return None
            
            # 计算统计信息
            total_chunks = len(chunks)
            total_content_length = sum(len(chunk["content"]) for chunk in chunks)
            
            # 获取创建时间范围
            if chunks[0].get("created_at"):
                created_at = chunks[0]["created_at"]
            else:
                created_at = None
            
            stats = {
                "document_id": doc_id,
                "total_chunks": total_chunks,
                "total_content_length": total_content_length,
                "average_chunk_length": total_content_length / total_chunks if total_chunks > 0 else 0,
                "created_at": created_at,
                "chunks": chunks  # 可选：包含所有分块
            }
            
            return stats
            
        except Exception as e:
            error_msg = f"获取文档统计信息失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _delete_document_chunks(self, doc_id: str):
        """内部方法：删除文档的所有分块"""
        try:
            response = self.supabase.table("document_chunks").delete().eq("document_id", doc_id).execute()
            logger.debug(f"已删除文档 {doc_id} 的所有旧分块")
        except Exception as e:
            logger.warning(f"删除文档旧分块失败: {str(e)}")
            # 这里不抛出异常，因为可能是第一次保存，没有旧分块

    def _is_valid_chunk(self, chunk_data: Dict) -> bool:
        """检查分块是否有效"""
        content = chunk_data.get("content", "")
        
        # 1. 内容不能为空
        if not content or len(content.strip()) == 0:
            return False
        
        # 2. 内容不能太短（可根据需要调整）
        if len(content.strip()) < 10:
            logger.debug(f"内容过短: {len(content.strip())} 字符")
            return False
        
        # 3. 可以添加更多检查规则
        # 例如：检查是否包含大量元数据关键词
        metadata_keywords = ["metadata", "header", "footer", "page", "title", "作者", "日期"]
        content_lower = content.lower()
        if any(keyword in content_lower for keyword in metadata_keywords):
            # 如果内容主要是元数据，可以跳过
            logger.debug(f"内容可能包含元数据: {content[:50]}...")
            return False
        
        return True

    def _format_vector_for_db(self, vector: List[float]) -> str:
        """将向量格式化为数据库存储格式（PostgreSQL vector类型）"""
        if not vector:
            return "[]"
        
        # PostgreSQL vector 类型期望格式: "[0.1,0.2,0.3]"
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        return vector_str

    def _parse_vector_from_db(self, vector_data) -> List[float]:
        """从数据库解析向量数据"""
        if vector_data is None:
            return []
        
        # 如果是字符串，解析它
        if isinstance(vector_data, str):
            # 移除方括号并分割
            vector_str = vector_data.strip()
            if vector_str.startswith('['):
                vector_str = vector_str[1:]
            if vector_str.endswith(']'):
                vector_str = vector_str[:-1]
            
            # 转换为浮点数列表
            return [float(x) for x in vector_str.split(',')]
        
        # 如果已经是列表，直接返回
        elif isinstance(vector_data, list):
            return vector_data
        
        # 其他情况返回空列表
        return []

    # 为了向后兼容，保留原来的 save 和 get 方法，但修改其实现
    def save(self, doc_id: str, chunks: List[Dict]):
        """向后兼容的保存方法"""
        return self.save_document_chunks(doc_id, chunks)

    def get(self, doc_id: str):
        """向后兼容的获取方法（返回文档的所有分块）"""
        return self.get_document_chunks(doc_id)