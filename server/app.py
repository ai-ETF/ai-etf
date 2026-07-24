from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

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

# 现在导入其他模块，这时环境变量已经可用
from server.api.upload import router as upload_router
from server.api.ask import router as ask_router
from server.api.test import router as test_router  # 添加test路由
from server.api.market import router as market_router  # 添加market路由（新增）
from server.api.watchlist import router as watchlist_router  # 添加watchlist路由（新增）
from server.api.secure_chat import router as secure_chat_router  # 添加secure_chat路由（JWT认证）
from server.auth import get_current_user
from server.config.settings import SETTINGS

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

    # 检查 JWT Secret 配置
    if not SETTINGS.SUPABASE_JWT_SECRET:
        logger.warning("SUPABASE_JWT_SECRET 未配置，JWT 认证将无法工作")
    else:
        logger.info("JWT Secret 配置检查通过")

    # 启动定时刷新行情缓存任务
    from server.services.finance_api_service import FinanceApiService
    scheduler = AsyncIOScheduler()

    # 统一定时任务：每30秒检查并刷新（refresh_spot_cache 内部根据交易时段决定是否实际拉取）
    # 非交易时段：跳过刷新（保留旧缓存），避免无效拉取
    scheduler.add_job(
        FinanceApiService.refresh_spot_cache,
        trigger=IntervalTrigger(seconds=30),
        id="refresh_etf_spot",
        name="刷新ETF全量行情缓存（交易时段30s/非交易时段跳过）",
        replace_existing=True,
    )
    logger.info("ETF行情定时刷新任务已注册（每30秒检测一次）")

    scheduler.start()

    # 立即执行第一次热加载（不阻塞启动）
    asyncio.ensure_future(_warmup_cache())

    yield  # 应用在此处运行

    scheduler.shutdown(wait=False)
    logger.info("ETF行情定时刷新任务已停止")
    logger.info("应用关闭")


async def _warmup_cache():
    """启动时异步预热行情缓存"""
    from server.services.finance_api_service import FinanceApiService
    logger.info("[预热] 开始首次全量行情加载...")
    success = FinanceApiService.refresh_spot_cache()
    if success:
        logger.info("[预热] 全量行情加载完成")
    else:
        logger.warning("[预热] 全量行情加载失败，将等待定时任务重试")


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
app.include_router(test_router, prefix="/api", tags=["test"])  # 重新添加test路由
app.include_router(market_router, prefix="/api/market", tags=["market"], dependencies=[Depends(get_current_user)])  # 添加market路由（新增）
app.include_router(watchlist_router, prefix="/api/watchlist", tags=["watchlist"], dependencies=[Depends(get_current_user)])  # 添加watchlist路由（新增）
app.include_router(secure_chat_router, prefix="/api", tags=["secure-chat"])  # 添加secure_chat路由（JWT认证）

@app.get("/")
def read_root():
    return {"Hello": "World"}

# 支持直接运行：python server/app.py
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)