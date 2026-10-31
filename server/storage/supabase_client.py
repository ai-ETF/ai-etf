import os
import logging
import threading
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None


logger = logging.getLogger(__name__)

# 进程内复用的数据客户端。每次 create_client 都会重新建立连接，实测本地约 450ms，
# 持仓页一次加载若每个请求都新建，光建连就占掉大半耗时。
#
# 注意：这个客户端必须始终保持 service_role 身份。supabase-py 在执行
# auth.sign_in_with_password / sign_up / refresh_session 之后，会把客户端
# 的 Authorization 头改成该用户的 JWT，并重建底层 postgrest 客户端。
# 一旦在共享客户端上登录，整个进程后续所有请求都会以最后登录用户的身份
# 访问数据库（丢失 service_role、RLS 生效、跨用户串数据）。
# 因此所有登录类操作必须使用 get_auth_client()，禁止对这个客户端调用 auth 登录方法。
_client: "Client | None" = None
_client_lock = threading.Lock()


def _get_credentials():
    """读取并校验 Supabase 连接配置，返回 (url, key)；缺失时返回 (None, None)。"""
    url = os.getenv("SUPABASE_URL")
    # 优先使用service_role key
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not url:
        logger.error("未设置SUPABASE_URL环境变量")
        return None, None

    if not key:
        logger.error("未设置SUPABASE_SERVICE_ROLE_KEY或SUPABASE_KEY环境变量")
        return None, None

    if create_client is None:
        logger.error("Supabase客户端库未正确安装")
        return None, None

    return url, key


def get_supabase():
    """返回进程内复用的 Supabase 数据客户端（首次调用时创建）。

    只用于读写业务表，必须保持 service_role 身份；登录/注册/刷新等会改写
    Authorization 头的操作请使用 get_auth_client()。

    创建失败（环境变量缺失/库未安装/连不上）不缓存，下次调用会重试。
    """
    global _client
    if _client is not None:
        return _client

    url, key = _get_credentials()
    if not url:
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


def get_auth_client():
    """新建一个独立的 Supabase 客户端，专用于登录类操作。

    每次调用都新建、不缓存，用完即弃：supabase-py 的 sign_in / sign_up /
    refresh_session 会改写该客户端的 Authorization 头，如果复用就会污染
    全进程的数据客户端（见上）。登录属于低频操作，多付一次建连成本可以接受。

    创建失败返回 None，由调用方按「数据库未就绪」处理。
    """
    url, key = _get_credentials()
    if not url:
        return None

    try:
        return create_client(url, key)
    except Exception as e:
        logger.error(f"Supabase认证客户端初始化失败: {str(e)}")
        return None
