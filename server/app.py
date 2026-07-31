from contextlib import asynccontextmanager  # 用于定义应用生命周期（启动/关闭）
from fastapi import FastAPI  # Web 框架核心
from fastapi.middleware.cors import CORSMiddleware  # 跨域中间件
import os  # 路径拼接、环境变量读取
import logging  # 日志
import warnings  # 抑制第三方库 deprecation warning

# 抑制 langgraph-checkpoint 内部 deprecation warning（不影响功能）
warnings.filterwarnings("ignore", message="The default value of `allowed_objects`",
                        category=DeprecationWarning)

def init_logging():
    """初始化日志系统"""
    # 获取日志级别，默认为DEBUG
    log_level_str = os.getenv("LOG_LEVEL", "DEBUG").upper()
    log_level = getattr(logging, log_level_str, logging.DEBUG)
    
    # 配置根日志记录器
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    else:
        # 如果已经有处理器，更新根日志记录器的级别
        logging.getLogger().setLevel(log_level)
    
    # 设置第三方库的日志级别，避免过多的调试信息
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    logging.info(f"日志系统初始化完成，级别: {log_level_str}")


# 首先加载环境变量
try:
    from dotenv import load_dotenv
    # 计算当前文件的上级目录的上级目录，即项目根目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))  # server/
    project_root_dir = os.path.dirname(current_file_dir)          # ai-etf/
    dotenv_path = os.path.join(project_root_dir, '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.info("环境变量从 .env 文件加载成功")
except ImportError:
    logging.warning("python-dotenv 未安装，跳过从 .env 文件加载环境变量")
except Exception as e:
    logging.error(f"从 .env 文件加载环境变量失败: {e}")

# 初始化日志系统
init_logging()

# 导入路由模块（此时环境变量已加载，各模块初始化时能正确读取配置）
from server.api import router as api_router  # 聚合路由（所有子模块通过 __init__.py 注册）
from server.config.settings import SETTINGS  # 全局配置（环境变量集中管理）

logger = logging.getLogger(__name__)
logger.setLevel(SETTINGS.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期事件处理"""
    logger.info("应用启动，验证Supabase连接")
    from server.storage.supabase_client import get_supabase
    supabase = get_supabase()
    if not supabase:
        error_msg = "Supabase连接失败，应用无法启动"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    logger.info("Supabase连接验证成功")

    # 启动行情缓存调度器（交易时段每30秒拉取全量行情）
    from server.services.spot_cache_scheduler import start_scheduler as start_spot_scheduler, shutdown_scheduler as shutdown_spot_scheduler
    start_spot_scheduler()

    yield  # 应用在此处运行

    shutdown_spot_scheduler()
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

# 注册聚合路由（所有子模块通过 server/api/__init__.py 统一注册）
app.include_router(api_router, prefix="/api")

@app.get("/")
def read_root():
    return {"Hello": "World"}

# 支持直接运行：python server/app.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)