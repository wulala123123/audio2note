"""
文件名: endpoints.py
功能描述: FastAPI 路由端点，处理视频上传和任务状态查询
核心逻辑:
    - POST /tasks/upload: 接收视频文件，创建后台处理任务
    - GET /tasks/{task_id}/status: 轮询任务处理进度
    - 后台任务编排 PPT 提取与音频转录两个独立模块
"""
import uuid
import shutil
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from app.services.video_service import VideoService
from app.services.files_service import secure_delete
from app.core.config import TEMP_DIR
from app.core.task_manager import (
    init_task, 
    update_task_progress, 
    get_task_status, 
    complete_task, 
    fail_task
)

router = APIRouter()


# ============================================================
#                   后台任务处理函数
# ============================================================
async def run_video_task(
    task_id: str, 
    temp_file_path: Path, 
    enable_ppt_extraction: bool,
    enable_audio_transcription: bool
) -> None:
    """
    后台视频处理任务的核心编排函数
    
    该函数在 FastAPI 的 BackgroundTasks 中异步执行，负责:
    1. 调用 VideoService 处理视频
    2. 根据处理结果更新任务状态
    3. 清理临时文件
    
    Args:
        task_id: 任务唯一标识符 (UUID)
        temp_file_path: 上传视频的临时存储路径
        enable_ppt_extraction: 是否执行 PPT 提取流程
        enable_audio_transcription: 是否执行音频转录流程
    
    Note:
        两个功能模块完全解耦，可独立启用或同时启用
    """
    logger.info("=" * 60)
    logger.info(f"🎬 开始处理任务: {task_id}")
    logger.info(f"   📂 文件路径: {temp_file_path.name}")
    logger.info(f"   📊 PPT 提取: {'✅ 启用' if enable_ppt_extraction else '❌ 禁用'}")
    logger.info(f"   🎤 音频转录: {'✅ 启用' if enable_audio_transcription else '❌ 禁用'}")
    logger.info("=" * 60)
    
    try:
        update_task_progress(task_id, 0, "等待处理资源...")
        
        # 创建视频处理服务实例
        # Why 每次创建新实例?
        #   - 每个任务拥有独立的输出目录
        #   - 避免状态污染
        service = VideoService(output_guid=task_id)
        
        # 在线程池中运行 CPU/GPU 密集型任务
        # Why run_in_threadpool?
        #   - FastAPI 的事件循环不应被阻塞
        #   - 视频处理包含大量同步 I/O 和计算
        result = await run_in_threadpool(
            service.process, 
            temp_file_path, 
            enable_ppt_extraction=enable_ppt_extraction,
            enable_audio_transcription=enable_audio_transcription
        )
        
        # ========== 结果处理 ==========
        ppt_url = None
        transcript_url = None
        
        if result.get("ppt_file"):
            ppt_filename = Path(result["ppt_file"]).name
            ppt_url = f"/static/{task_id}/ppt_output/{ppt_filename}"
            logger.success(f"📄 PPT 生成成功: {ppt_url}")
        
        if result.get("transcript_file"):
            transcript_filename = Path(result["transcript_file"]).name
            transcript_url = f"/static/{task_id}/transcripts/{transcript_filename}"
            logger.success(f"📝 转录文件生成成功: {transcript_url}")
        
        # 只要有一个输出就算成功
        if ppt_url or transcript_url:
            complete_task(task_id, ppt_url, transcript_url=transcript_url)
            logger.success(f"✨ 任务 {task_id} 处理完成!")
        else:
            fail_task(task_id, "未能生成任何输出结果")
            logger.error(f"❌ 任务 {task_id} 失败: 无输出")
            
    except Exception as e:
        logger.exception(f"❌ 任务 {task_id} 处理异常")
        fail_task(task_id, str(e))
    finally:
        # 清理临时上传文件
        await secure_delete(temp_file_path)
        logger.debug(f"🗑️ 已清理临时文件: {temp_file_path.name}")
        logger.info("=" * 60)
        logger.info(f"🏁 任务 {task_id} 处理流程结束")
        logger.info("=" * 60)


# ============================================================
#                   API 端点: 上传视频
# ============================================================
@router.post("/tasks/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="待处理的视频文件"),
    enable_ppt_extraction: bool = Form(True, description="是否启用 PPT 提取"),
    enable_audio_transcription: bool = Form(True, description="是否启用音频转录")
) -> dict:
    """
    上传视频并创建异步处理任务
    
    该端点接收视频文件，保存到临时目录后立即返回任务 ID，
    实际处理在后台异步进行。前端通过轮询状态端点获取进度。
    
    Args:
        background_tasks: FastAPI 后台任务管理器
        file: 上传的视频文件 (multipart/form-data)
        enable_ppt_extraction: 是否执行 PPT 提取 (默认 True)
        enable_audio_transcription: 是否执行音频转录 (默认 True)
    
    Returns:
        dict: 包含 task_id 和初始状态
        
    Raises:
        HTTPException(400): 未选择任何处理功能
        HTTPException(500): 文件保存失败
    
    Example:
        >>> curl -X POST -F "file=@lecture.mp4" -F "enable_ppt_extraction=true" \\
        ...      http://127.0.0.1:8000/api/v1/tasks/upload
        {"task_id": "xxx-xxx", "status": "processing", "message": "任务已提交"}
    """
    logger.info("=" * 60)
    logger.info("📥 收到视频上传请求")
    logger.info(f"   📁 文件名: {file.filename}")
    logger.info(f"   📊 PPT 提取: {enable_ppt_extraction}")
    logger.info(f"   🎤 音频转录: {enable_audio_transcription}")
    
    # ========== 参数校验 ==========
    # 业务规则: 至少选择一项处理功能
    if not enable_ppt_extraction and not enable_audio_transcription:
        logger.warning("⚠️ 请求被拒绝: 未选择任何处理功能")
        raise HTTPException(
            status_code=400, 
            detail="至少选择一项处理功能 (PPT提取 或 音频转录)"
        )
    
    # ========== 创建任务 ==========
    task_id = str(uuid.uuid4())
    init_task(task_id)
    logger.info(f"   🆔 生成任务 ID: {task_id}")

    # ========== 保存临时文件 ==========
    temp_file_path = TEMP_DIR / f"{task_id}_{file.filename}"
    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.debug(f"   💾 临时文件已保存: {temp_file_path}")
    except Exception as e:
        logger.error(f"❌ 文件保存失败: {e}")
        fail_task(task_id, f"文件保存失败: {str(e)}")
        raise HTTPException(status_code=500, detail="文件上传失败")

    # ========== 加入后台队列 ==========
    background_tasks.add_task(
        run_video_task, 
        task_id, 
        temp_file_path, 
        enable_ppt_extraction,
        enable_audio_transcription
    )
    logger.success(f"✅ 任务 {task_id} 已加入后台队列")
    logger.info("=" * 60)
    
    return {
        "task_id": task_id,
        "status": "processing",
        "message": "任务已提交"
    }


# ============================================================
#                   API 端点: 查询任务状态
# ============================================================
@router.get("/tasks/{task_id}/status")
async def get_status(task_id: str) -> dict:
    """
    查询指定任务的处理状态和进度
    
    前端通过轮询此端点获取任务进度，建议轮询间隔 1-2 秒。
    
    Args:
        task_id: 任务唯一标识符
        
    Returns:
        dict: 包含 status, progress, message, result_url 等字段
        
    Raises:
        HTTPException(404): 任务不存在
    
    Response Schema:
        {
            "status": "processing" | "completed" | "failed",
            "progress": 0-100,
            "message": "当前处理阶段描述",
            "result_url": "PPT 下载链接 (完成后)",
            "transcript_url": "转录文件链接 (如启用)",
            "error": "错误信息 (失败时)"
        }
    """
    status = get_task_status(task_id)
    
    if not status:
        logger.warning(f"⚠️ 查询不存在的任务: {task_id}")
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 日志: 仅在关键节点打印，避免轮询日志过多
    if status.get("progress") in [0, 50, 100] or status.get("status") in ["completed", "failed"]:
        logger.debug(f"📊 任务 {task_id[:8]}... 状态: {status.get('status')} ({status.get('progress')}%)")
    
    return status
