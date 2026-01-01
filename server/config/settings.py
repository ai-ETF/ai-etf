import os
import logging


# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class Settings:
    """
    应用配置类
    管理应用的各种配置参数，包括数据库连接信息、嵌入维度等
    """
    
    def __init__(self):
        """
        初始化配置参数
        从环境变量中读取配置值，如果未设置则使用默认值
        """
        # Supabase数据库连接URL
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        # Supabase数据库连接密钥
        self.SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if self.SUPABASE_URL and self.SUPABASE_KEY:
            logger.info("检测到Supabase配置，将使用Supabase作为主要存储")
        else:
            if not self.SUPABASE_URL:
                logger.warning("未配置SUPABASE_URL环境变量")
            if not self.SUPABASE_KEY:
                logger.warning("未配置SUPABASE_KEY环境变量")
            logger.warning("由于缺少Supabase配置，将使用SQLite作为存储（但当前已禁用SQLite回退机制）")
        
        # 数据库文件路径，默认为"server_data.db"
        self.DB_PATH = os.getenv("ETFSERVER_DB_PATH", "server_data.db")
        # 嵌入向量维度，设置为1536维以匹配数据库
        self.EMBED_DIM = int(os.getenv("ETFSERVER_EMBED_DIM", "1536"))
        
        logger.info(f"配置加载完成: DB_PATH={self.DB_PATH}, EMBED_DIM={self.EMBED_DIM}")


# 创建全局配置实例
SETTINGS = Settings()