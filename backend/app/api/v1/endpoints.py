# filename: backend/app/api/v1/endpoints.py
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.concurrency import run_in_threadpool

from app.services.video_service import VideoService
from app.services.files_service import secure_delete
from app.core.config import TEMP_DIR
from app.core.task_manager import init_task, update_task_progress, get_task_status, complete_task, fail_task

router = APIRouter()

async def run_video_task(task_id: str, temp_file_path: Path, enable_transcription: bool):
    """后台任务逻辑"""
    try:
        update_task_progress(task_id, 0, "等待处理资源...")
        
        service = VideoService(output_guid=task_id)
        
        # 在线程池中运行 OpenCV (CPU密集)
        # 注意: run_in_threadpool 默认只接受位置参数，如果需要关键字参数可能需要用 functools.partial 或 lambda
        # 这里 VideoService.process 定义为 process(self, input_video_path, enable_transcription=False)
        # 简单起见，我们可以包装一下或者直接传参如果 run_in_threadpool 支持 (FastAPI context: generally supports *args, **kwargs)
        # Verify: run_in_threadpool(func, *args, **kwargs) -> Yes.
        result = await run_in_threadpool(service.process, temp_file_path, enable_transcription=enable_transcription)
        
        # 结果处理
        if result and result.get("ppt_file"):
            # 构造下载链接: /static/{task_id}/ppt_output/{task_id}.pptx
            ppt_filename = Path(result["ppt_file"]).name
            # 注意: 这里假设 backend/output 挂载为 /static
            # 实际文件路径: backend/output/{task_id}/ppt_output/xxx.pptx
            download_url = f"/static/{task_id}/ppt_output/{ppt_filename}"
            
            # 处理字幕链接
            transcript_url = None
            if result.get("transcript_file"):
                transcript_filename = Path(result["transcript_file"]).name
                # /static/{task_id}/transcripts/{task_id}.txt
                transcript_url = f"/static/{task_id}/transcripts/{transcript_filename}"
            
            complete_task(task_id, download_url, transcript_url=transcript_url)
        else:
            fail_task(task_id, "PPT 生成结果为空")
            
    except Exception as e:
        fail_task(task_id, str(e))
    finally:
        await secure_delete(temp_file_path)

@router.post("/tasks/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_transcription: bool = Form(False)
):
    """
    1. 上传视频
    2. 创建后台任务
    3. 返回 task_id
    """
    task_id = str(uuid.uuid4())
    init_task(task_id)

    # 保存临时文件
    temp_file_path = TEMP_DIR / f"{task_id}_{file.filename}"
    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        fail_task(task_id, f"文件保存失败: {str(e)}")
        raise HTTPException(status_code=500, detail="文件上传失败")

    # 加入后台队列
    background_tasks.add_task(run_video_task, task_id, temp_file_path, enable_transcription)
    
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "任务已提交"
    }

@router.get("/tasks/{task_id}/status")
async def get_status(task_id: str):
    """
    轮询任务进度
    """
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status
