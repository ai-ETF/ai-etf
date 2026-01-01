import os
import logging
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def get_supabase():
    url = os.getenv("SUPABASE_URL")
    # 优先使用service_role key
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not url:
        logger.error("未设置SUPABASE_URL环境变量")
        return None
        
    if not key:
        logger.error("未设置SUPABASE_SERVICE_ROLE_KEY或SUPABASE_KEY环境变量")
        return None
        
    if create_client is None:
        logger.error("Supabase客户端库未正确安装")
        return None
        
    try:
        client = create_client(url, key)
        logger.info("Supabase客户端初始化成功")
        return client
    except Exception as e:
        logger.error(f"Supabase客户端初始化失败: {str(e)}")
        return None