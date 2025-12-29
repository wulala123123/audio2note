# filename: backend/server.py
import shutil
import asyncio
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
import aiofiles

# 导入我们的处理模块 (确保 crop_ppt.py 和 extract_ppt.py 在同一目录下)
from . import crop_ppt
from . import extract_ppt

app = FastAPI(title="Video2PPT Backend")

# 设定基础路径
# server.py 在 backend/ 目录下，input/output 在 backend/ 的父目录 (项目根目录)
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
INPUT_DIR = PROJECT_ROOT / 'input'
OUTPUT_DIR = PROJECT_ROOT / 'output'

# 确保目录存在
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def process_video_task(video_path: Path):
    """
    后台任务处理函数：
    1. 调用 crop_ppt 进行裁剪
    2. 如果裁剪成功，调用 extract_ppt 提取PPT
    """
    try:
        print(f"Background Task Started: Processing {video_path.name}")
        
        # 1. 裁剪视频
        # crop_ppt.process_video 返回裁剪后的视频路径 (Path 对象) 或 None
        cropped_video_path = crop_ppt.process_video(video_path, OUTPUT_DIR)
        
        if not cropped_video_path:
            print(f"Task Failed: Scaling/Cropping failed for {video_path.name}")
            return

        print(f"Cropping Successful: {cropped_video_path}")

        # 2. 提取PPT
        # extract_ppt.extract_key_frames_persistent_reference 返回生成的 PPT 路径 (Path 对象) 或 None
        ppt_path = extract_ppt.extract_key_frames_persistent_reference(
            video_path=cropped_video_path, 
            output_base_dir=OUTPUT_DIR
        )

        if ppt_path:
            print(f"Task Completed Successfully: PPT generated at {ppt_path}")
        else:
            print(f"Task Warning: No keyframes extracted for {video_path.name}")

    except Exception as e:
        print(f"Task Error: An unexpected error occurred while processing {video_path.name}: {e}")

@app.post("/process")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    接收上传的视频文件，保存后启动后台处理任务。
    """
    # 验证文件扩展名
    filename = file.filename
    if not filename:
         raise HTTPException(status_code=400, detail="Invalid filename")

    file_ext = Path(filename).suffix.lower()
    allowed_extensions = {'.mp4', '.m4s', '.avi', '.mov', '.mkv'}
    
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed_extensions}")

    # 保存文件到 input 目录
    # 为了防止文件名冲突，可以使用 uuid 重命名，这里简单起见使用原文件名
    # 但建议在生产环境中处理文件名冲突
    save_path = INPUT_DIR / filename
    
    try:
        async with aiofiles.open(save_path, 'wb') as out_file:
            # 这里的 read/write 需要分块处理大文件，aiofiles + shutil 配合
            # 或者直接循环读取 chunks
            while content := await file.read(1024 * 1024):  # 1MB chunks
                await out_file.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # 添加后台任务
    background_tasks.add_task(process_video_task, save_path)

    return {
        "message": "File uploaded successfully. Processing started in background.",
        "filename": filename,
        "saved_path": str(save_path)
    }

@app.get("/")
def read_root():
    return {"message": "Video2PPT Backend is running. POST to /process to start."}
