import os
import logging
import threading
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None


logger = logging.getLogger(__name__)

# 进程内复用的客户端。每次 create_client 都会重新建立连接，实测本地约 450ms，
# 持仓页一次加载若每个请求都新建，光建连就占掉大半耗时。
_client: "Client | None" = None
_client_lock = threading.Lock()


def get_supabase():
    """返回进程内复用的 Supabase 客户端（首次调用时创建）。

    创建失败（环境变量缺失/库未安装/连不上）不缓存，下次调用会重试。
    """
    global _client
    if _client is not None:
        return _client

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

    with _client_lock:
        # 双重检查：并发首次请求只创建一个客户端
        if _client is not None:
            return _client
        try:
            _client = create_client(url, key)
            logger.info("Supabase客户端初始化成功")
            return _client
        except Exception as e:
            logger.error(f"Supabase客户端初始化失败: {str(e)}")
            return None