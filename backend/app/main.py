# filename: backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.endpoints import router as api_router

from contextlib import asynccontextmanager
from app.services.audio_service import init_audio_service
import logging

# 配置 logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: 初始化模型
    logger.info("Application Startup: Initializing heavy services...")
    init_audio_service()
    yield
    # Shutdown: Clean up if needed
    logger.info("Application Shutdown")

app = FastAPI(title="Video-to-PPT API", version="1.0.0", lifespan=lifespan)

# CORS 配置：允许 React 前端调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议修改为具体的 frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from app.core.config import OUTPUT_DIR

# 注册路由
app.include_router(api_router, prefix="/api/v1")

# 挂载静态文件 (用于下载 PPT)
app.mount("/static", StaticFiles(directory=OUTPUT_DIR), name="static")

@app.get("/")
async def root():
    return {"message": "Video-to-PPT Backend Service is Running"}
