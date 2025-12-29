# filename: backend/app/core/config.py
import os
from pathlib import Path

# 定位 backend 根目录 (假设 config.py 在 backend/app/core/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 临时文件夹
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 输出文件夹
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 允许上传的视频格式
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4s"}
