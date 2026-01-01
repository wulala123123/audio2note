"""
文件名: main.py
功能描述: FastAPI 应用入口，负责应用生命周期管理与全局日志配置
核心逻辑:
    - 配置 loguru 日志系统 (控制台 + 文件)
    - lifespan 上下文管理器：启动时预加载 FunASR 模型
    - 挂载静态文件目录，注册 API 路由
"""
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.endpoints import router as api_router
from app.core.config import OUTPUT_DIR
from app.services.audio_service import init_audio_service


# ============================================================
#                    日志配置 (Loguru)
# ============================================================
def setup_logging():
    """
    配置 loguru 日志系统
    
    日志输出规则:
        - 控制台: 彩色输出，INFO 级别以上
        - 文件: JSON 格式，DEBUG 级别以上，按天轮转
    
    Loguru 的优势:
        - 自动彩色输出，无需额外配置
        - 支持结构化日志 (serialize=True 生成 JSON)
        - 内置异常回溯美化
    """
    # 移除默认的 handler
    logger.remove()
    
    # 控制台输出: 彩色格式，便于开发调试
    # format 参数说明:
    #   {time:HH:mm:ss} - 时间戳 (时:分:秒)
    #   {level.icon} - 日志级别图标 (如 🐛 ✅ ⚠️)
    #   {module}:{function}:{line} - 代码位置
    #   {message} - 日志内容
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level.icon} {level: <8}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True,
        backtrace=True,  # 显示完整异常调用栈
        diagnose=True    # 显示变量值 (仅开发环境)
    )
    
    # 文件输出: 按天轮转，保留 7 天
    # Why 文件日志?
    #   - 生产环境排查问题时，控制台日志可能已丢失
    #   - 文件日志可搜索、可持久化
    logger.add(
        "logs/backend_{time:YYYY-MM-DD}.log",
        rotation="00:00",    # 每天午夜轮转
        retention="7 days",  # 保留 7 天
        compression="zip",   # 旧日志压缩
        level="DEBUG",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {module}:{function}:{line} - {message}"
    )
    
    logger.info("✅ 日志系统初始化完成")


# 应用启动时调用
setup_logging()


# ============================================================
#                   应用生命周期管理
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期上下文管理器
    
    Startup (yield 之前):
        - 预加载 FunASR 语音识别模型
        - 模型加载耗时约 10-30 秒，首次运行需下载权重
    
    Shutdown (yield 之后):
        - 清理资源 (如有需要)
    
    Why 使用 lifespan 而非 on_event?
        - FastAPI 官方推荐的新方式
        - 支持异步上下文管理
        - 更清晰的资源管理语义
    """
    logger.info("=" * 60)
    logger.info("🚀 Video2Note 后端服务启动中...")
    logger.info("=" * 60)
    
    # Startup: 初始化耗时服务
    logger.info("📦 正在预加载 AI 模型 (FunASR)...")
    init_audio_service()
    logger.success("✨ 所有服务初始化完成，准备接收请求")
    
    yield  # 应用运行中
    
    # Shutdown: 清理资源
    logger.info("=" * 60)
    logger.info("👋 Video2Note 后端服务关闭中...")
    
    # ========== GPU 显存释放 ==========
    # Why 在 shutdown 阶段清理?
    #   - 确保服务优雅关闭时释放所有 GPU 资源
    #   - 避免热重载时显存累积占用
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.debug("🧹 PyTorch GPU 显存已释放")
    except ImportError:
        pass
    
    try:
        import paddle
        if paddle.device.is_compiled_with_cuda():
            paddle.device.cuda.empty_cache()
            logger.debug("🧹 PaddlePaddle GPU 显存已释放")
    except ImportError:
        pass
    
    logger.info("=" * 60)


# ============================================================
#                   FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="Video2Note API",
    description="视频转 PPT + 语音转文字服务",
    version="2.0.0",
    lifespan=lifespan
)

# CORS 中间件: 允许前端跨域访问
# Why allow_origins=["*"]?
#   - 开发环境便于调试
#   - 生产环境应修改为具体的前端域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router, prefix="/api/v1")

# 挂载静态文件目录
# 用途: 提供 PPT 和转录文件的下载链接
# URL 示例: /static/{task_id}/ppt_output/xxx.pptx
app.mount("/static", StaticFiles(directory=OUTPUT_DIR), name="static")


@app.get("/")
async def root():
    """
    根路径健康检查端点
    
    Returns:
        dict: 服务状态信息
    """
    return {
        "service": "Video2Note Backend",
        "status": "running",
        "version": "2.0.0"
    }
