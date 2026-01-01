from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # 导入CORS中间件，用于处理跨域请求
import logging

from server.api import ask, upload, test
from server.storage.setup_supabase_tables import setup_supabase_tables

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 创建FastAPI应用实例，设置标题
app = FastAPI(title="ETF RAG Server")

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


@app.on_event('startup')
def startup_event():
    """应用启动时的事件处理"""
    logger.info("应用启动，验证Supabase表结构")
    setup_supabase_tables()


@app.get("/hello")
def hello():
    """
    简单的测试端点，用于验证服务器是否正常运行
    返回: {"message": "Hello World"}
    """
    return {"message": "Hello World"}