import json
from typing import Optional, List, Dict
import logging
from datetime import datetime
from server.storage.supabase_client import get_supabase

# 配置日志
logging.basicConfig(level=logging.DEBUG)
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

    def save_document_metadata(self, doc_id: str, url: str, source: Optional[str] = None, title: Optional[str] = None):
        """保存文档元数据到 documents 表"""
        logger.debug(f"保存文档元数据，ID: {doc_id}, URL: {url}, 来源: {source}, 标题: {title}")
        
        try:
            # 准备元数据
            metadata_entry = {
                "document_id": doc_id,
                "url": url,
                "source": source,
                "title": title or f"Document {doc_id}",
                "created_at": datetime.utcnow().isoformat() + "Z"  # ISO格式，带时区
            }
            
            # 检查是否已存在相同的 document_id
            existing_response = self.supabase.table("documents").select("*").eq("document_id", doc_id).execute()
            
            if existing_response.data and len(existing_response.data) > 0:
                # 已存在，更新记录
                metadata_id = existing_response.data[0]["id"]
                update_data = {
                    "url": url,
                    "source": source,
                    "title": title or existing_response.data[0].get("title", f"Document {doc_id}"),
                    "updated_at": datetime.utcnow().isoformat() + "Z"
                }
                
                response = self.supabase.table("documents").update(update_data).eq("id", metadata_id).execute()
                logger.debug(f"文档 {doc_id} 元数据已更新")
            else:
                # 不存在，插入新记录
                response = self.supabase.table("documents").insert(metadata_entry).execute()
                logger.debug(f"文档 {doc_id} 元数据已插入")
            
            if response.data and len(response.data) > 0:
                metadata_id = response.data[0]["id"]
                logger.debug(f"文档元数据操作成功，metadata_id: {metadata_id}")
                return metadata_id
            else:
                logger.error("保存文档元数据失败，无返回数据")
                return None
                
        except Exception as e:
            error_msg = f"Supabase保存文档元数据失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def save_document_chunk(self, doc_id: str, chunk_index: int, content: str, 
                           embedding: List[float], metadata_id: Optional[str] = None,
                           document_name: Optional[str] = None, document_type: Optional[str] = None,
                           page_number: int = 1):
        """保存单个文档分块到 document_chunks 表"""
        logger.debug(f"保存文档分块，文档ID: {doc_id}, 块索引: {chunk_index}, 内容长度: {len(content)}")
        
        try:
            # 如果没有 metadata_id，尝试从 documents 表获取
            if not metadata_id:
                metadata_id = self._get_metadata_id_by_doc_id(doc_id)
            
            # 准备分块数据
            chunk_data = {
                "document_id": doc_id,
                "document_metadata_id": metadata_id,
                "document_name": document_name or f"chunk_{doc_id}_{chunk_index}",
                "document_type": document_type or "text_chunk",
                "chunk_index": chunk_index,
                "content": content,
                "embedding": self._format_vector_for_db(embedding),
                "page_number": page_number,
                "is_metadata": False,
                "created_at": datetime.utcnow().isoformat() + "Z"
            }
            
            # 检查是否已存在相同的文档分块
            existing_response = self.supabase.table("document_chunks").select("*").eq("document_id", doc_id).eq("chunk_index", chunk_index).execute()
            
            if existing_response.data and len(existing_response.data) > 0:
                # 已存在，更新记录
                chunk_id = existing_response.data[0]["id"]
                response = self.supabase.table("document_chunks").update(chunk_data).eq("id", chunk_id).execute()
                logger.debug(f"文档分块 {doc_id}.{chunk_index} 已更新")
            else:
                # 不存在，插入新记录
                response = self.supabase.table("document_chunks").insert(chunk_data).execute()
                logger.debug(f"文档分块 {doc_id}.{chunk_index} 已插入")
            
            if response.data and len(response.data) > 0:
                chunk_id = response.data[0]["id"]
                logger.debug(f"文档分块保存成功，chunk_id: {chunk_id}")
                return chunk_id
            else:
                logger.error(f"保存文档分块失败，无返回数据")
                return None
                
        except Exception as e:
            error_msg = f"Supabase保存文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def save_document_chunks_batch(self, doc_id: str, chunks: List[Dict], 
                                  metadata_id: Optional[str] = None,
                                  document_name: Optional[str] = None, 
                                  document_type: Optional[str] = None):
        """批量保存文档分块到 document_chunks 表"""
        logger.debug(f"批量保存文档分块，文档ID: {doc_id}, 块数: {len(chunks)}")
        
        try:
            # 如果没有 metadata_id，尝试从 documents 表获取
            if not metadata_id:
                metadata_id = self._get_metadata_id_by_doc_id(doc_id)
            
            # 准备批量数据
            chunks_data = []
            for i, chunk in enumerate(chunks):
                chunk_data = {
                    "document_id": doc_id,
                    "document_metadata_id": metadata_id,
                    "document_name": document_name or f"chunk_{doc_id}_{i}",
                    "document_type": document_type or chunk.get("document_type", "text_chunk"),
                    "chunk_index": i,
                    "content": chunk.get("text", ""),
                    "embedding": self._format_vector_for_db(chunk.get("embedding", [])),
                    "page_number": chunk.get("page", 1),
                    "is_metadata": False,
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }
                chunks_data.append(chunk_data)
            
            # 批量插入
            if chunks_data:
                # 首先删除该文档的所有旧分块（可选，根据需求）
                # self.supabase.table("document_chunks").delete().eq("document_id", doc_id).execute()
                
                # 批量插入新分块
                response = self.supabase.table("document_chunks").insert(chunks_data).execute()
                logger.debug(f"成功批量插入 {len(chunks_data)} 个文档块")
                return True
            else:
                logger.warning("没有文档分块需要保存")
                return False
                
        except Exception as e:
            error_msg = f"Supabase批量保存文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_document_metadata(self, doc_id: str):
        """从 documents 表获取文档元数据"""
        logger.debug(f"获取文档元数据，ID: {doc_id}")
        
        try:
            response = self.supabase.table("documents").select("*").eq("document_id", doc_id).execute()
            
            if response.data and len(response.data) > 0:
                row = response.data[0]
                result = {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "url": row.get("url", ""),
                    "source": row.get("source", ""),
                    "title": row.get("title", ""),
                    "created_at": row.get("created_at", ""),
                    "updated_at": row.get("updated_at", "")
                }
                logger.debug(f"文档 {doc_id} 元数据获取完成")
                return result
            else:
                logger.debug(f"文档 {doc_id} 在documents表中不存在")
                return None
                
        except Exception as e:
            error_msg = f"Supabase获取文档元数据失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_document_chunks(self, doc_id: str, exclude_metadata: bool = True):
        """获取文档的所有分块"""
        logger.debug(f"获取文档分块，文档ID: {doc_id}")
        
        try:
            query = self.supabase.table("document_chunks").select("*").eq("document_id", doc_id)
            
            if exclude_metadata:
                query = query.eq("is_metadata", False)
            
            query = query.order("chunk_index")
            response = query.execute()
            
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
                        "metadata_id": row.get("document_metadata_id"),
                        "created_at": row.get("created_at", "")
                    }
                    chunks.append(chunk)
            
            logger.debug(f"获取到 {len(chunks)} 个文档分块")
            return chunks
            
        except Exception as e:
            error_msg = f"Supabase获取文档分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_document_with_chunks(self, doc_id: str):
        """获取文档元数据及其所有分块"""
        logger.debug(f"获取文档及其分块，ID: {doc_id}")
        
        try:
            # 获取元数据
            metadata = self.get_document_metadata(doc_id)
            if not metadata:
                return None
            
            # 获取分块
            chunks = self.get_document_chunks(doc_id)
            
            result = {
                "metadata": metadata,
                "chunks": chunks,
                "total_chunks": len(chunks)
            }
            
            logger.debug(f"文档 {doc_id} 及其 {len(chunks)} 个分块获取完成")
            return result
            
        except Exception as e:
            error_msg = f"获取文档及其分块失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def delete_document(self, doc_id: str):
        """删除文档及其所有分块"""
        logger.debug(f"删除文档，ID: {doc_id}")
        
        try:
            # 由于设置了外键级联删除，删除documents表中的记录会自动删除document_chunks表中的相关记录
            response = self.supabase.table("documents").delete().eq("document_id", doc_id).execute()
            
            if response.data:
                logger.debug(f"文档 {doc_id} 删除成功")
                return True
            else:
                logger.debug(f"文档 {doc_id} 不存在，无需删除")
                return False
                
        except Exception as e:
            error_msg = f"Supabase删除文档失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def search_documents_by_source(self, source: str):
        """根据来源搜索文档"""
        logger.debug(f"根据来源搜索文档，来源: {source}")
        
        try:
            response = self.supabase.table("documents").select("*").eq("source", source).execute()
            
            documents = []
            if response.data:
                for row in response.data:
                    document = {
                        "id": row["id"],
                        "document_id": row["document_id"],
                        "url": row.get("url", ""),
                        "source": row.get("source", ""),
                        "title": row.get("title", ""),
                        "created_at": row.get("created_at", "")
                    }
                    documents.append(document)
            
            logger.debug(f"找到 {len(documents)} 个来源为 {source} 的文档")
            return documents
            
        except Exception as e:
            error_msg = f"Supabase根据来源搜索文档失败: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _get_metadata_id_by_doc_id(self, doc_id: str) -> str:
        """根据 document_id 获取 metadata_id"""
        try:
            response = self.supabase.table("documents").select("id").eq("document_id", doc_id).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]["id"]
            else:
                # 如果没有找到，创建一个新的文档记录
                logger.warning(f"文档 {doc_id} 的元数据不存在，正在创建默认元数据...")
                
                # 创建默认元数据
                metadata_entry = {
                    "document_id": doc_id,
                    "title": f"Document {doc_id}",
                    "created_at": datetime.utcnow().isoformat() + "Z"
                }
                
                create_response = self.supabase.table("documents").insert(metadata_entry).execute()
                
                if create_response.data and len(create_response.data) > 0:
                    return create_response.data[0]["id"]
                else:
                    raise ValueError(f"无法为文档 {doc_id} 创建元数据记录")
                    
        except Exception as e:
            logger.error(f"获取文档元数据ID失败: {str(e)}")
            raise RuntimeError(f"获取文档元数据ID失败: {str(e)}")

    def _format_vector_for_db(self, vector: List[float]) -> str:
        """将向量格式化为数据库存储格式（PostgreSQL vector类型）"""
        if not vector:
            return "[]"
        
        # PostgreSQL vector 类型期望格式: "[0.1,0.2,0.3]"
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
        return vector_str

    # 为了向后兼容，保留原来的 save 和 get 方法，但修改其实现
    def save(self, doc_id: str, url: str, text: str, source: Optional[str] = None):
        """向后兼容的保存方法（仅保存元数据）"""
        logger.warning("使用旧版save方法，建议使用save_document_metadata方法替代")
        return self.save_document_metadata(doc_id, url, source)

    def get(self, doc_id: str):
        """向后兼容的获取方法（仅获取元数据）"""
        logger.warning("使用旧版get方法，建议使用get_document_metadata方法替代")
        metadata = self.get_document_metadata(doc_id)
        if metadata:
            # 为了保持接口兼容，返回类似旧格式的数据
            return {
                "id": metadata["document_id"],
                "url": metadata.get("url", ""),
                "source": metadata.get("source", None),
                "text": ""  # 旧版本返回文本，新版不存储完整文本
            }
        return None