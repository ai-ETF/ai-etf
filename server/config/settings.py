import os


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
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        # 数据库文件路径，默认为"server_data.db"
        self.DB_PATH = os.getenv("ETFSERVER_DB_PATH", "server_data.db")
        # 嵌入向量维度，默认为128
        self.EMBED_DIM = int(os.getenv("ETFSERVER_EMBED_DIM", "128"))


# 创建全局配置实例
SETTINGS = Settings()