# filename: backend/app/api/v1/endpoints.py
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services.video_service import VideoService
from app.services.files_service import secure_delete
from app.core.config import TEMP_DIR

router = APIRouter()

@router.post("/process-video")
async def process_video(file: UploadFile = File(...)):
    """
    上传视频并自动提取为 PPT
    """
    # 1. 生成唯一 ID
    request_id = str(uuid.uuid4())
    temp_file_path = TEMP_DIR / f"{request_id}_{file.filename}"
    
    try:
        # 2. 保存上传文件
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # 3. 初始化服务
        service = VideoService(output_guid=request_id)
        
        # 4. 在线程池中运行 CPU 密集型任务 (OpenCV)
        # 避免阻塞 FastAPI 的主事件循环
        result = await run_in_threadpool(service.process, temp_file_path)
        
        return {
            "status": "success",
            "data": result,
            "message": "视频处理完成"
        }

    except Exception as e:
        # 错误处理
        return {
            "status": "error",
            "message": str(e)
        }
        
    finally:
        # 5. 清理临时上传的视频文件
        # 使用 secure_delete 避免 Windows 文件占用问题
        await secure_delete(temp_file_path)
