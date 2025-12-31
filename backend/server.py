# filename: backend/server.py
import uuid
import shutil
import logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

# 导入应用模块
from app.services.video_service import VideoService
from app.core.task_manager import init_task, get_task_status, fail_task, complete_task
from app.core.config import INPUT_DIR, OUTPUT_DIR, ALLOWED_EXTENSIONS

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video2PPT Backend API")

# 允许跨域 (方便前端调用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录，以便前端可以直接访问生成的 PPT 和图片
# 访问地址: http://localhost:8000/static/output/...
app.mount("/static/output", StaticFiles(directory=OUTPUT_DIR), name="static_output")

def run_video_processing(task_id: str, video_path: Path, enable_transcription: bool):
    """
    后台任务包装函数：执行视频处理并在完成后更新任务状态。
    """
    try:
        logger.info(f"Task {task_id}: 开始处理视频 {video_path.name}, 字幕={enable_transcription}")
        
        # 初始化服务
        service = VideoService(output_guid=task_id)
        
        # 执行处理 (耗时操作)
        result = service.process(video_path, enable_transcription=enable_transcription)
        
        # 生成结果的 Web 访问 URL
        # 假设 result['ppt_file'] 是绝对路径，我们需要转换为相对 /static 的 URL
        ppt_url = None
        transcript_url = None
        
        if result.get("ppt_file"):
            ppt_name = Path(result["ppt_file"]).name
            # 结构: output/{task_id}/ppt_output/{name}
            # 但 VideoService 的 process 返回的是绝对路径
            # 我们的静态挂载点是 output 根目录
            # 所以 URL 应该是 /static/output/{task_id}/ppt_output/{ppt_name}
            ppt_url = f"/static/output/{task_id}/ppt_output/{ppt_name}"
            
        if result.get("transcript_file"):
            txt_name = Path(result["transcript_file"]).name
            transcript_url = f"/static/output/{task_id}/transcripts/{txt_name}"
            
        # 标记任务完成
        complete_task(task_id, result_url=ppt_url, transcript_url=transcript_url)
        logger.info(f"Task {task_id}: 处理完成")
        
    except Exception as e:
        logger.error(f"Task {task_id}: 处理失败 - {e}")
        fail_task(task_id, str(e))

@app.post("/process")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    enable_transcription: bool = Form(False)
):
    """
    接收视频上传，启动后台处理任务。
    返回 task_id 用于轮询进度。
    """
    filename = file.filename
    if not filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    file_ext = Path(filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式. 允许: {ALLOWED_EXTENSIONS}")

    # 生成唯一的任务 ID
    task_id = str(uuid.uuid4())
    
    # 定义保存路径
    save_path = INPUT_DIR / f"{task_id}_{filename}"
    
    try:
        # 保存文件
        async with aiofiles.open(save_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                await out_file.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    # 初始化任务状态
    init_task(task_id)
    
    # 添加到后台任务队列
    background_tasks.add_task(run_video_processing, task_id, save_path, enable_transcription)

    return {
        "message": "视频已上传，后台处理中",
        "task_id": task_id,
        "filename": filename
    }

@app.get("/task/{task_id}")
def query_task_status(task_id: str):
    """
    查询任务处理进度和结果
    """
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status

@app.get("/")
def read_root():
    return {"message": "Video2PPT Backend Service is Running"}

if __name__ == "__main__":
    import uvicorn
    # 为了开发方便，可以直接运行此文件
    uvicorn.run(app, host="0.0.0.0", port=8000)
