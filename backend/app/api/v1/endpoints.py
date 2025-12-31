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

async def run_video_task(
    task_id: str, 
    temp_file_path: Path, 
    enable_ppt_extraction: bool,
    enable_audio_transcription: bool
):
    """
    后台任务逻辑
    
    Args:
        task_id: 任务唯一标识
        temp_file_path: 临时视频文件路径
        enable_ppt_extraction: 是否启用 PPT 提取
        enable_audio_transcription: 是否启用音频转录
    """
    try:
        update_task_progress(task_id, 0, "等待处理资源...")
        
        service = VideoService(output_guid=task_id)
        
        # 调用解耦后的 process 方法，传递两个独立开关
        result = await run_in_threadpool(
            service.process, 
            temp_file_path, 
            enable_ppt_extraction=enable_ppt_extraction,
            enable_audio_transcription=enable_audio_transcription
        )
        
        # 结果处理: 任一功能成功产出即为成功
        ppt_url = None
        transcript_url = None
        
        if result.get("ppt_file"):
            ppt_filename = Path(result["ppt_file"]).name
            ppt_url = f"/static/{task_id}/ppt_output/{ppt_filename}"
        
        if result.get("transcript_file"):
            transcript_filename = Path(result["transcript_file"]).name
            transcript_url = f"/static/{task_id}/transcripts/{transcript_filename}"
        
        # 只要有一个输出就算成功
        if ppt_url or transcript_url:
            complete_task(task_id, ppt_url, transcript_url=transcript_url)
        else:
            fail_task(task_id, "未能生成任何输出结果")
            
    except Exception as e:
        fail_task(task_id, str(e))
    finally:
        await secure_delete(temp_file_path)

@router.post("/tasks/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_ppt_extraction: bool = Form(True),
    enable_audio_transcription: bool = Form(False)
):
    """
    上传视频并创建处理任务
    
    Args:
        file: 视频文件
        enable_ppt_extraction: 是否启用 PPT 提取 (默认启用)
        enable_audio_transcription: 是否启用音频转录 (默认禁用)
    
    Returns:
        task_id 和任务状态
    """
    # 参数校验: 至少选择一项功能
    if not enable_ppt_extraction and not enable_audio_transcription:
        raise HTTPException(status_code=400, detail="至少选择一项处理功能")
    
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

    # 加入后台队列，传递两个独立开关
    background_tasks.add_task(
        run_video_task, 
        task_id, 
        temp_file_path, 
        enable_ppt_extraction,
        enable_audio_transcription
    )
    
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
