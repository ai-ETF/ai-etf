import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

# 首先加载环境变量
try:
    from dotenv import load_dotenv
    # 计算当前文件的上级目录的上级目录，即项目根目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))  # server/
    project_root_dir = os.path.dirname(current_file_dir)          # ai-etf/
    dotenv_path = os.path.join(project_root_dir, '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.basicConfig(level=logging.INFO)
    logging.info("环境变量从 .env 文件加载成功")
except ImportError:
    logging.basicConfig(level=logging.INFO)
    logging.warning("python-dotenv 未安装，跳过从 .env 文件加载环境变量")
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logging.error(f"从 .env 文件加载环境变量失败: {e}")

# 现在导入其他模块，这时环境变量已经可用
from server.api.upload import router as upload_router
from server.api.ask import router as ask_router
from server.config.settings import SETTINGS

logger = logging.getLogger(__name__)

# 设置第三方库的日志级别，避免过多的调试信息
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# 显式导入并使用别名
from server.api.ask import router as ask_router
from server.api.upload import router as upload_router
from server.api.test import router as test_router
from server.storage.supabase_client import get_supabase

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(SETTINGS.LOG_LEVEL if hasattr(SETTINGS, 'LOG_LEVEL') else logging.INFO)


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

    yield  # 应用在此处运行

    logger.info("应用关闭")


# 创建FastAPI应用实例
app = FastAPI(title="AI-ETF Server", lifespan=lifespan, debug=True)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该限制为特定的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由，并添加标签用于文档分类
app.include_router(upload_router, prefix="/api", tags=["upload"])
app.include_router(ask_router, prefix="/api", tags=["ask"])
app.include_router(test_router, prefix="/api", tags=["test"])

@app.get("/")
def read_root():
    return {"Hello": "World"}

# 支持直接运行：python server/app.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)