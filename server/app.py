import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # 导入CORS中间件，用于处理跨域请求
import logging
from contextlib import asynccontextmanager

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    # 使用相对路径，基于当前工作目录
    # __file__ 是当前文件(server/app.py)的路径
    # os.path.dirname(__file__) 得到 server 目录
    # os.path.dirname(os.path.dirname(__file__)) 得到项目根目录
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.info("环境变量从 .env 文件加载成功")
except ImportError:
    logging.warning("python-dotenv 未安装，跳过从 .env 文件加载环境变量")
except Exception as e:
    logging.error(f"从 .env 文件加载环境变量失败: {e}")

from server.api import ask, upload, test
from server.storage.supabase_client import get_supabase

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件处理"""
    logger.info("应用启动，验证Supabase连接")
    supabase = get_supabase()
    if not supabase:
        error_msg = "Supabase连接失败，应用无法启动"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    logger.info("Supabase连接验证成功")
    
    yield  # 在这里应用运行
    
    # 关闭时的清理工作可以放在这里
    logger.info("应用关闭")


# 创建FastAPI应用实例，设置标题
app = FastAPI(title="ETF RAG Server", lifespan=lifespan)

# 添加CORS中间件，允许跨域请求（在生产环境中应限制为具体域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应替换为具体域名列表
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由，前缀为/api
app.include_router(upload.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
# 注册测试路由，前缀为/test
app.include_router(test.router, prefix="/test")


@app.get("/hello")
def hello():
    """
    简单的测试端点，用于验证服务器是否正常运行
    返回: {"message": "Hello World"}
    """
    return {"message": "Hello World"}