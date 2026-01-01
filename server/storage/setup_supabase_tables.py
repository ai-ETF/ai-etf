import logging
from server.storage.supabase_client import get_supabase


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def setup_supabase_tables():
    """
    设置Supabase表结构
    """
    logger.info("开始设置Supabase表结构")
    supabase = get_supabase()
    
    if not supabase:
        logger.error("无法连接到Supabase，请检查环境变量SUPABASE_URL和SUPABASE_SERVICE_ROLE_KEY是否已设置")
        return False

    try:
        # 验证documents表是否可访问
        logger.info("验证documents表...")
        response = supabase.table("documents").select("id").limit(1).execute()
        logger.info("documents表已存在或可访问")
        
        # 验证document_chunks表是否可访问
        logger.info("验证document_chunks表...")
        response = supabase.table("document_chunks").select("id").limit(1).execute()
        logger.info("document_chunks表已存在或可访问")
        
        logger.info("Supabase表结构验证完成")
        return True
        
    except Exception as e:
        logger.error(f"验证Supabase表结构时出错: {str(e)}")
        logger.info("请确保您已在Supabase项目中创建了以下表结构：")
        print("""
documents 表结构:
- id (uuid, 主键)
- url (text)
- source (text)
- text (text)
- created_at (timestamptz, 默认为当前时间)

document_chunks 表结构 (您的现有表):
- id (uuid, 主键)
- document_id (uuid) - 外键关联documents表
- document_name (text)
- document_type (text)
- chunk_index (int4)
- content (text)
- embedding (vector) - 用于向量搜索
- page_number (int4)
- created_at (timestamptz, 默认为当前时间)
        """)
        return False


if __name__ == "__main__":
    setup_supabase_tables()