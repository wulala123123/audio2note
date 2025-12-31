"""
文件名: config.py
功能描述: 全局配置模块，定义路径常量和应用配置
核心逻辑:
    - 使用 pathlib 处理路径，确保 Windows/Linux 兼容性
    - 自动创建必要的目录结构
    - 定义允许上传的文件格式白名单
"""
from pathlib import Path


# ============================================================
#              路径配置
# ============================================================
# 定位 backend 根目录
# 假设 config.py 在 backend/app/core/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 临时文件夹: 存放上传的视频文件
# 处理完成后会自动清理
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 输出文件夹: 按 task_id 组织的处理结果
# 目录结构:
#   output/{task_id}/
#       ├── cropped_video/   # 裁剪后的视频
#       ├── debug_images/    # 边缘检测调试图
#       ├── ppt_images/      # PPT 页面截图
#       ├── ppt_output/      # 最终 PPTX 文件
#       └── transcripts/     # 转录文本文件
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#              上传配置
# ============================================================
# 允许上传的视频格式白名单
# 包含常见的视频容器格式
ALLOWED_EXTENSIONS = {
    ".mp4",   # H.264/H.265 + AAC
    ".mov",   # Apple QuickTime
    ".avi",   # AVI 容器
    ".mkv",   # Matroska (支持多音轨/字幕)
    ".m4s",   # MPEG-DASH 分片
}
