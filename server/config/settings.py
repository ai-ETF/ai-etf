import os
import logging


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
        # 获取日志级别，默认为DEBUG
        log_level_str = os.getenv("LOG_LEVEL", "DEBUG").upper()
        log_level = getattr(logging, log_level_str, logging.DEBUG)
        
        self.LOG_LEVEL = log_level
        
        # Supabase数据库连接URL
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        # Supabase数据库连接密钥
        self.SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        if self.SUPABASE_URL and self.SUPABASE_KEY:
            logging.info("检测到Supabase配置，将使用Supabase作为主要存储")
        else:
            if not self.SUPABASE_URL:
                logging.warning("未配置SUPABASE_URL环境变量")
            if not self.SUPABASE_KEY:
                logging.warning("未配置SUPABASE_SERVICE_ROLE_KEY环境变量")
            logging.warning("由于缺少Supabase配置，将使用SQLite作为存储（但当前已禁用SQLite回退机制）")
        
        # 数据库文件路径，默认为"server_data.db"
        self.DB_PATH = os.getenv("ETFSERVER_DB_PATH", "server_data.db")
        # 嵌入向量维度，设置为768维以匹配数据库
        self.EMBED_DIM = int(os.getenv("ETFSERVER_EMBED_DIM", "768"))

        # === LangGraph / Lyra 配置 ===
        # Anthropic API 密钥
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        # Lyra 使用的模型
        self.LYRA_MODEL = os.getenv("LYRA_MODEL", "claude-sonnet-4-20250514")
        # Lyra 最大 token 数
        self.LYRA_MAX_TOKENS = int(os.getenv("LYRA_MAX_TOKENS", "4096"))

        # === XiaoYan 配置 ===
        # 数据缓存时间（秒），默认 1 天
        self.XIAOYAN_CACHE_TTL = int(os.getenv("XIAOYAN_CACHE_TTL", "86400"))
        # 数据收集超时（秒）
        self.XIAOYAN_TIMEOUT = int(os.getenv("XIAOYAN_TIMEOUT", "30"))

        # === JWT 认证配置（对接 Supabase Auth）===
        # Supabase 项目的 JWT Secret，在 Supabase 控制台 Settings > API > JWT Secret 获取
        self.SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

        # === 情绪检测配置 ===
        self.EMOTION_DETECTION_ENABLED = os.getenv("EMOTION_DETECTION_ENABLED", "true").lower() == "true"

        logging.info(f"配置加载完成: DB_PATH={self.DB_PATH}, EMBED_DIM={self.EMBED_DIM}, LOG_LEVEL={log_level_str}")


def configure_logging():
    """在应用启动时配置日志"""
    log_level_str = os.getenv("LOG_LEVEL", "DEBUG").upper()
    log_level = getattr(logging, log_level_str, logging.DEBUG)
    
    # 只有在尚未配置日志处理器时才进行配置
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )


# 在模块加载时配置日志（应用启动时）
configure_logging()

# 创建全局配置实例
SETTINGS = Settings()