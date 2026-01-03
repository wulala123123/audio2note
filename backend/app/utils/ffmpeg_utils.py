"""
文件名: ffmpeg_utils.py
功能描述: FFmpeg 封装模块，提供健壮的视频处理工具函数
核心逻辑:
    - generate_lightweight_video(): 生成低分辨率轻量视频 (640px, 5fps)
    - extract_frame_at_timestamp(): 从原视频精确截取指定时间点画面
    - GPU (h264_nvenc) → CPU (libx264) 自动回退机制

设计亮点:
    - 所有函数基于时间戳 (seconds float)，严禁依赖 frame_index
    - 完整的 try-except 和 fallback 机制
    - 实时进度解析支持
"""
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

from loguru import logger


# ============================================================
#              FFmpeg 编码器检测
# ============================================================

def _check_nvenc_available() -> bool:
    """
    检测系统是否支持 NVENC 硬件编码
    
    通过运行 `ffmpeg -encoders` 并解析输出来判断。
    
    Returns:
        bool: True 表示 h264_nvenc 可用
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return "h264_nvenc" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ============================================================
#              轻量视频生成
# ============================================================

def generate_lightweight_video(
    source_video: Path,
    output_path: Path,
    crop_box: Tuple[int, int, int, int],
    target_width: int = 640,
    target_fps: int = 5,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Optional[Path]:
    """
    生成轻量视频 (Lightweight Media) - 核心优化函数
    
    对原视频进行裁剪、缩放、降帧处理，生成用于后续分析的轻量级视频。
    极大提升 L1/L2/L3 漏斗模型的处理速度。
    
    FFmpeg 滤镜链:
        crop={w}:{h}:{x}:{y} → scale={width}:-1 → fps={fps}
    
    Args:
        source_video: 原始视频路径
        output_path: 轻量视频输出路径
        crop_box: 裁剪区域 (x, y, w, h)
            - 来自 ROI 检测的 PPT 区域
        target_width: 缩放目标宽度 (高度自适应)
            - 默认 640px，足够进行内容分析
        target_fps: 目标帧率
            - 默认 5 FPS，足够检测 PPT 翻页
        progress_callback: 进度回调函数
            - 签名: callback(percent: int, message: str)
    
    Returns:
        Path: 生成的轻量视频路径，失败返回 None
    
    Note:
        自动尝试 GPU 编码 (h264_nvenc)，失败则回退到 CPU (libx264)
    """
    source_video = Path(source_video)
    output_path = Path(output_path)
    
    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    x, y, w, h = crop_box
    
    # ========== NVENC 兼容性修正 ==========
    # h264_nvenc 要求宽高为偶数，scale 滤镜自动处理高度
    # 但 crop 的 x, y, w, h 必须手动对齐
    original_box = (x, y, w, h)
    x = (x // 2) * 2
    y = (y // 2) * 2
    w = (w // 2) * 2
    h = (h // 2) * 2
    
    if (x, y, w, h) != original_box:
        logger.debug(f"📐 crop_box 对齐偶数: {original_box} → ({x}, {y}, {w}, {h})")
    
    # ========== 构建滤镜链 ==========
    # Why scale=-2 而非 -1?
    #   -2 确保输出高度也是偶数，避免某些编码器报错
    vf_filter = f"crop={w}:{h}:{x}:{y},scale={target_width}:-2,fps={target_fps}"
    
    # 首先尝试 GPU 编码
    success = _run_ffmpeg_encode(
        source_video=source_video,
        output_path=output_path,
        vf_filter=vf_filter,
        use_gpu=True,
        progress_callback=progress_callback
    )
    
    if success:
        return output_path
    
    # GPU 失败，回退到 CPU
    logger.warning("⚠️ GPU 编码失败，尝试 CPU 回退...")
    if progress_callback:
        progress_callback(0, "GPU 编码失败，切换 CPU 模式...")
    
    success = _run_ffmpeg_encode(
        source_video=source_video,
        output_path=output_path,
        vf_filter=vf_filter,
        use_gpu=False,
        progress_callback=progress_callback
    )
    
    if success:
        return output_path
    
    logger.error("❌ 轻量视频生成失败 (GPU/CPU 均失败)")
    return None


def _run_ffmpeg_encode(
    source_video: Path,
    output_path: Path,
    vf_filter: str,
    use_gpu: bool = True,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> bool:
    """
    执行 FFmpeg 编码命令
    
    内部函数，封装 GPU/CPU 两种编码模式的命令构建和执行。
    
    Args:
        source_video: 输入视频
        output_path: 输出路径
        vf_filter: 视频滤镜链 (crop → scale → fps)
        use_gpu: 是否使用 GPU 编码
        progress_callback: 进度回调
    
    Returns:
        bool: 编码是否成功
    """
    mode_str = "GPU (h264_nvenc)" if use_gpu else "CPU (libx264)"
    logger.info(f"🎬 开始生成轻量视频 [{mode_str}]")
    logger.info(f"   📂 输入: {source_video.name}")
    logger.info(f"   📂 输出: {output_path.name}")
    logger.info(f"   🔧 滤镜: {vf_filter}")
    
    # ========== 构建命令 ==========
    cmd = [
        "ffmpeg",
        "-y",  # 覆盖已存在文件
        "-i", str(source_video),
        "-vf", vf_filter,
    ]
    
    if use_gpu:
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", "p1",  # NVENC 最快预设
            "-cq", "28",      # 质量控制 (轻量视频可容忍更高压缩)
        ])
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",  # CPU 最快预设
            "-crf", "28",
        ])
    
    cmd.extend([
        "-pix_fmt", "yuv420p",
        "-an",  # 去除音频
        str(output_path)
    ])
    
    logger.debug(f"   命令: {' '.join(cmd)}")
    
    start_time = time.time()
    
    try:
        # ========== 异步执行并解析进度 ==========
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        # FFmpeg 进度解析正则
        # 格式: time=00:01:23.45
        time_pattern = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
        
        # 获取视频总时长 (用于计算进度百分比)
        total_duration = _get_video_duration(source_video)
        
        stderr_lines = []
        last_progress_time = time.time()
        
        for line in process.stderr:
            stderr_lines.append(line)
            
            # 解析时间进度
            match = time_pattern.search(line)
            if match and total_duration > 0:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = float(match.group(3))
                current_time = hours * 3600 + minutes * 60 + seconds
                
                percent = min(99, int((current_time / total_duration) * 100))
                
                # 限制回调频率 (每 1 秒最多一次)
                now = time.time()
                if progress_callback and now - last_progress_time >= 1.0:
                    progress_callback(percent, f"生成轻量视频: {percent}%")
                    last_progress_time = now
        
        process.wait()
        elapsed = time.time() - start_time
        
        if process.returncode == 0:
            logger.success(f"✅ 轻量视频生成完成 [{mode_str}] 耗时: {elapsed:.1f}s")
            if progress_callback:
                progress_callback(100, "轻量视频生成完成")
            return True
        else:
            stderr_text = ''.join(stderr_lines)
            stderr_tail = stderr_text[-500:] if len(stderr_text) > 500 else stderr_text
            logger.error(f"❌ FFmpeg 失败 [{mode_str}] returncode={process.returncode}")
            logger.debug(f"   stderr: {stderr_tail}")
            return False
            
    except FileNotFoundError:
        logger.error("❌ FFmpeg 未安装或不在 PATH 中")
        return False
    except Exception as e:
        logger.exception(f"❌ FFmpeg 执行异常: {e}")
        return False


def _get_video_duration(video_path: Path) -> float:
    """
    获取视频时长 (秒)
    
    使用 ffprobe 快速读取视频元数据。
    
    Args:
        video_path: 视频文件路径
    
    Returns:
        float: 视频时长 (秒)，失败返回 0
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning(f"⚠️ 无法获取视频时长: {video_path.name}")
        return 0.0


# ============================================================
#              高清帧截取
# ============================================================

def extract_frame_at_timestamp(
    source_video: Path,
    timestamp: float,
    output_path: Path,
    crop_box: Optional[Tuple[int, int, int, int]] = None
) -> Optional[Path]:
    """
    高清回溯: 从原视频精确截取指定时间点画面
    
    使用 FFmpeg 的 `-ss` 输入定位实现精确 seek，
    确保截取的帧与分析阶段确定的时间戳完全对应。
    
    Why 使用原视频?
        轻量视频是低分辨率的，最终 PPT 需要高清画面。
        通过时间戳锚点，从原视频截取可保留完整画质。
    
    Args:
        source_video: 原始 (未缩放) 视频路径
        timestamp: 目标时间点 (秒)
            - 由三层漏斗分析确定的最终时间戳
        output_path: 输出图片路径 (.jpg/.png)
        crop_box: 可选裁剪区域 (x, y, w, h)
            - 来自 ROI 检测的 PPT 区域
            - 如果提供，会在截取后裁剪
    
    Returns:
        Path: 截取的图片路径，失败返回 None
    """
    source_video = Path(source_video)
    output_path = Path(output_path)
    
    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # ========== 构建命令 ==========
    # Why `-ss` 在 `-i` 前面?
    #   输入定位 (input seeking) 比输出定位更快，
    #   FFmpeg 会跳过前面的帧而非解码后丢弃。
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{timestamp:.3f}",  # 精确到毫秒的时间戳
        "-i", str(source_video),
    ]
    
    # 添加裁剪滤镜 (如果提供了 crop_box)
    if crop_box:
        x, y, w, h = crop_box
        # 对齐偶数
        x = (x // 2) * 2
        y = (y // 2) * 2
        w = (w // 2) * 2
        h = (h // 2) * 2
        cmd.extend(["-vf", f"crop={w}:{h}:{x}:{y}"])
    
    cmd.extend([
        "-frames:v", "1",  # 只截取 1 帧
        "-q:v", "2",       # JPEG 质量 (1-31, 2 为高质量)
        str(output_path)
    ])
    
    logger.debug(f"📸 截取帧 @ {timestamp:.2f}s → {output_path.name}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and output_path.exists():
            return output_path
        else:
            logger.warning(f"⚠️ 帧截取失败 @ {timestamp:.2f}s: {result.stderr[-200:]}")
            return None
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ 帧截取超时 @ {timestamp:.2f}s")
        return None
    except FileNotFoundError:
        logger.error("❌ FFmpeg 未安装或不在 PATH 中")
        return None
    except Exception as e:
        logger.exception(f"❌ 帧截取异常 @ {timestamp:.2f}s: {e}")
        return None


# ============================================================
#              批量高清帧截取
# ============================================================

def extract_frames_batch(
    source_video: Path,
    timestamps: list[float],
    output_dir: Path,
    crop_box: Optional[Tuple[int, int, int, int]] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> list[Path]:
    """
    批量截取多个时间点的高清帧
    
    遍历时间戳列表，逐个调用 extract_frame_at_timestamp。
    
    Args:
        source_video: 原始视频路径
        timestamps: 目标时间戳列表 (秒)
        output_dir: 输出目录
        crop_box: 可选裁剪区域
        progress_callback: 进度回调
    
    Returns:
        list[Path]: 成功截取的图片路径列表
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results: list[Path] = []
    total = len(timestamps)
    
    logger.info(f"📸 开始批量高清回溯: 共 {total} 个时间点")
    
    for i, ts in enumerate(timestamps):
        # 生成输出文件名: slide_0001_12.345s.jpg
        output_path = output_dir / f"slide_{i:04d}_{ts:.2f}s.jpg"
        
        frame_path = extract_frame_at_timestamp(
            source_video=source_video,
            timestamp=ts,
            output_path=output_path,
            crop_box=crop_box
        )
        
        if frame_path:
            results.append(frame_path)
            logger.debug(f"   ✅ [{i+1}/{total}] @ {ts:.2f}s")
        else:
            logger.warning(f"   ❌ [{i+1}/{total}] @ {ts:.2f}s 失败")
        
        # 进度回调
        if progress_callback:
            percent = int(((i + 1) / total) * 100)
            progress_callback(percent, f"高清回溯: {i+1}/{total}")
    
    logger.success(f"✅ 批量截取完成: {len(results)}/{total} 成功")
    return results
