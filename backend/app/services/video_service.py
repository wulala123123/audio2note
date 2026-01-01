"""
文件名: video_service.py
功能描述: 视频处理核心服务，实现 GPU 加速的 PPT 提取与音频转录编排
核心逻辑:
    - _locate_ppt_region(): 使用 Canny 边缘检测定位视频中的 PPT 区域
    - _crop_video_ffmpeg(): FFmpeg NVENC 硬件加速裁剪视频
    - _extract_ppt_gpu_pipeline(): 三层漏斗 PPT 提取 (L1帧差 + L2清晰度 + L3 OCR去重)
    - process(): 主入口，编排 PPT 提取与音频转录两个独立模块

全链路架构:
    1. FFmpeg NVENC 硬件加速裁剪
    2. 三层漏斗模型 PPT 提取:
       - L1 物理层: GPU 帧差检测 (场景分割)
       - L2 质量层: 拉普拉斯清晰度择优 (选冠军帧)
       - L3 语义层: OCR 文本去重 (过滤重复页)

设计亮点:
    - 裁剪视频用于帧分析 (聚焦 PPT 区域，排除干扰)
    - 从原始视频截取最终画面 (保留完整质量和边界)
"""
import cv2
import shutil
import subprocess
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
from loguru import logger

from app.core.config import OUTPUT_DIR, TEMP_DIR
from app.core.task_manager import update_task_progress
from app.services.audio_service import get_audio_transcriber
from app.services.gpu_frame_processor import GPUFrameProcessor, BestShot
from app.services.ocr_deduper import OCRDeduper


class VideoService:
    """
    视频处理服务主类
    
    职责: 编排整个视频 -> PPT 转换流程，协调各子模块工作
    
    Attributes:
        output_guid: 任务唯一标识，用于组织输出目录
        base_output_path: 任务输出根目录
        frame_processor: GPU 帧处理器 (L1 + L2)
        ocr_deduper: OCR 语义去重器 (L3)
    
    Example:
        >>> service = VideoService(output_guid="task-123")
        >>> result = service.process(Path("lecture.mp4"), enable_ppt_extraction=True)
        >>> print(result["ppt_file"])
    """
    
    def __init__(self, output_guid: str) -> None:
        """
        初始化视频处理服务
        
        Args:
            output_guid: 任务唯一标识符 (通常为 UUID)
        """
        self.output_guid = output_guid
        self.base_output_path = OUTPUT_DIR / output_guid
        
        # 定义子目录结构
        self.cropped_dir = self.base_output_path / "cropped_video"
        self.debug_images_dir = self.base_output_path / "debug_images"
        self.ppt_images_dir = self.base_output_path / "ppt_images"
        self.ppt_output_dir = self.base_output_path / "ppt_output"
        self.transcripts_dir = self.base_output_path / "transcripts"
        
        # 创建所需文件夹
        for p in [self.cropped_dir, self.debug_images_dir, 
                  self.ppt_images_dir, self.ppt_output_dir, self.transcripts_dir]:
            p.mkdir(parents=True, exist_ok=True)
        
        logger.debug(f"📁 输出目录已创建: {self.base_output_path}")
        
        # ========== 初始化 GPU 处理器 (L1 + L2) ==========
        # 参数说明:
        #   diff_threshold: 帧间差异阈值，超过此值视为场景切换
        #   min_scene_duration: 场景最短持续时间，过滤动态视频片段
        #   sample_fps: 采样帧率，降低可节省算力
        self.frame_processor = GPUFrameProcessor(
            diff_threshold=0.12,
            min_scene_duration=1.5,
            sample_fps=4
        )
        
        # ========== 初始化 OCR 去重器 (L3) ==========
        # 参数说明:
        #   similarity_threshold: 文本相似度阈值，超过则判定为重复页
        self.ocr_deduper = OCRDeduper(
            similarity_threshold=0.90
        )

    def process(
        self, 
        input_video_path: Path, 
        enable_ppt_extraction: bool = True,
        enable_audio_transcription: bool = True
    ) -> dict:
        """
        视频处理主入口: 编排 PPT 提取与音频转录两个独立模块
        
        两个功能模块完全解耦，可独立启用或同时启用。
        进度条会根据启用的模块数量自动分配区间。
        
        Args:
            input_video_path: 原始视频文件路径
            enable_ppt_extraction: 是否执行 PPT 提取流程 (默认 True)
            enable_audio_transcription: 是否执行音频转录流程 (默认 False)
            
        Returns:
            dict: 处理结果，包含各输出文件路径
                - guid: 任务 ID
                - cropped_video: 裁剪后视频路径 (如启用 PPT 提取)
                - ppt_file: PPT 文件路径 (如启用 PPT 提取)
                - transcript_file: 转录文件路径 (如启用音频转录)
        
        Raises:
            ValueError: PPT 区域定位失败或视频裁剪失败
        """
        input_video_path = Path(input_video_path)
        
        logger.info("=" * 50)
        logger.info(f"🎬 VideoService.process() 开始处理")
        logger.info(f"   📂 输入: {input_video_path.name}")
        logger.info(f"   🆔 GUID: {self.output_guid}")
        logger.info(f"   📊 PPT提取: {enable_ppt_extraction} | 🎤 音频转录: {enable_audio_transcription}")
        logger.info("=" * 50)
        
        ppt_path = None
        transcript_path = None
        
        # ============================================================
        #               模块 1: PPT 提取 (条件执行)
        # ============================================================
        if enable_ppt_extraction:
            logger.info("📊 [PPT 提取模块] 开始执行...")
            
            # 进度区间分配:
            #   - 若同时启用音频: PPT 占 0-85%, 音频占 85-100%
            #   - 若仅 PPT: PPT 占 0-100%
            ppt_progress_end = 85 if enable_audio_transcription else 100
            
            # ----- Step 1.1: 定位 PPT 区域 -----
            update_task_progress(self.output_guid, 5, "正在定位 PPT 区域...")
            logger.info("🔍 Step 1.1: 定位 PPT 区域 (Canny 边缘检测)")
            
            bbox = self._locate_ppt_region(input_video_path)
            
            if not bbox:
                logger.error("❌ 无法定位 PPT 区域")
                raise ValueError("无法定位 PPT 区域，请确保视频中包含清晰的 PPT 画面")
            
            logger.success(f"✅ PPT 区域定位成功: x={bbox[0]}, y={bbox[1]}, w={bbox[2]}, h={bbox[3]}")
            
            # ----- Step 1.2: FFmpeg 硬件加速裁剪 -----
            update_task_progress(self.output_guid, 10, "正在裁剪视频 (GPU 加速)...")
            logger.info("✂️ Step 1.2: FFmpeg NVENC 硬件加速裁剪")
            
            cropped_video_path = self._crop_video_ffmpeg(input_video_path, bbox)
            
            if not cropped_video_path:
                logger.error("❌ 视频裁剪失败")
                raise ValueError("视频裁剪失败")
            
            logger.success(f"✅ 视频裁剪完成: {cropped_video_path.name}")
            
            # ----- Step 1.3: 三层漏斗 PPT 提取 -----
            logger.info("🎯 Step 1.3: 三层漏斗 PPT 提取 (L1→L2→L3)")
            
            ppt_path = self._extract_ppt_gpu_pipeline(
                cropped_video=cropped_video_path,
                original_video=input_video_path,
                crop_bbox=bbox
            )
            
            if ppt_path:
                logger.success(f"✅ PPT 提取完成: {ppt_path.name}")
            else:
                logger.warning("⚠️ PPT 提取完成但未生成文件")
        
        # ============================================================
        #               模块 2: 音频转录 (条件执行，完全独立)
        # ============================================================
        if enable_audio_transcription:
            logger.info("🎤 [音频转录模块] 开始执行...")
            
            # 进度区间:
            #   - 若同时启用 PPT: 从 85% 开始
            #   - 若仅音频: 从 0% 开始
            audio_progress_start = 85 if enable_ppt_extraction else 0
            
            update_task_progress(
                self.output_guid, 
                audio_progress_start + 5, 
                "正在进行语音识别 (FunASR)..."
            )
            
            try:
                logger.info("🔊 调用 FunASR 进行本地语音识别...")
                transcript_text = get_audio_transcriber().transcribe_video(input_video_path)
                
                if transcript_text:
                    transcript_path = self.transcripts_dir / f"{self.output_guid}.txt"
                    with open(transcript_path, "w", encoding="utf-8") as f:
                        f.write(transcript_text)
                    logger.success(f"✅ 转录文件已保存: {transcript_path.name}")
                    logger.debug(f"   📝 转录内容预览: {transcript_text[:100]}...")
                else:
                    logger.warning("⚠️ 转录结果为空")
                    
            except Exception as e:
                logger.exception(f"❌ 音频转录过程出错: {e}")
        
        # ========== 返回结果 ==========
        result = {
            "guid": self.output_guid,
            "cropped_video": str(self.cropped_dir / f"{self.output_guid}_cropped.mp4") if enable_ppt_extraction else None,
            "ppt_file": str(ppt_path) if ppt_path else None,
            "transcript_file": str(transcript_path) if transcript_path else None
        }
        
        logger.info("=" * 50)
        logger.info(f"🏁 VideoService.process() 处理完成")
        logger.info(f"   📄 PPT: {'✅ ' + ppt_path.name if ppt_path else '❌ 未生成'}")
        logger.info(f"   📝 转录: {'✅ ' + transcript_path.name if transcript_path else '❌ 未生成'}")
        logger.info("=" * 50)
        
        return result

    def _locate_ppt_region(self, video_path: Path) -> tuple | None:
        """
        定位视频中的 PPT 区域 (边缘检测法)
        
        算法策略:
            1. 在视频 20%/40%/60% 位置各采样一帧
            2. 使用 Canny 边缘检测识别边缘
            3. 使用轮廓分析寻找最大四边形区域
            4. 返回该区域的 bounding box
        
        Why 多点采样?
            - 视频开头/结尾可能没有 PPT 画面
            - 多点采样提高检测成功率
        
        Args:
            video_path: 输入视频路径
            
        Returns:
            tuple: (x, y, w, h) PPT 区域坐标和尺寸，失败返回 None
        """
        logger.debug(f"🔍 开始定位 PPT 区域: {video_path.name}")
        
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"❌ 无法打开视频: {video_path}")
            return None
        
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            sample_points = [0.2, 0.4, 0.6]  # 采样点: 20%, 40%, 60%
            
            logger.debug(f"   📊 总帧数: {total_frames}, 采样点: {sample_points}")
            
            for point in sample_points:
                frame_idx = int(total_frames * point)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                
                if not ret:
                    logger.warning(f"   ⚠️ 采样点 {point:.0%} 读取失败")
                    continue
                
                logger.debug(f"   🖼️ 分析采样点 {point:.0%} (帧 {frame_idx})")
                
                # 保存调试图像 (可视化边缘检测过程)
                cv2.imwrite(str(self.debug_images_dir / "0_original.jpg"), frame)
                
                # ----- Canny 边缘检测流水线 -----
                # Step 1: BGR -> Gray (减少计算量)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                cv2.imwrite(str(self.debug_images_dir / "1_gray.jpg"), gray)
                
                # Step 2: 高斯模糊 (去噪，平滑边缘)
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                
                # Step 3: Canny 边缘检测
                # Why (30, 120)? 低阈值 30 检测弱边缘，高阈值 120 过滤噪点
                edged = cv2.Canny(blurred, 30, 120)
                cv2.imwrite(str(self.debug_images_dir / "2_edged.jpg"), edged)
                
                # ----- 轮廓分析 -----
                contours, _ = cv2.findContours(
                    edged.copy(), 
                    cv2.RETR_EXTERNAL,      # 只检测外轮廓
                    cv2.CHAIN_APPROX_SIMPLE  # 压缩轮廓点
                )
                
                if not contours:
                    logger.debug(f"   ⚠️ 采样点 {point:.0%} 未找到轮廓")
                    continue
                
                # 取面积最大的 5 个轮廓 (PPT 通常是最大的矩形区域)
                contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
                
                for c in contours:
                    # 轮廓近似: 减少顶点数量
                    peri = cv2.arcLength(c, True)
                    approx = cv2.approxPolyDP(c, 0.03 * peri, True)
                    
                    # 筛选条件:
                    #   1. 必须是 4 边形 (PPT 是矩形)
                    #   2. 面积占比 > 10% (过滤小区域)
                    frame_area = frame.shape[0] * frame.shape[1]
                    area_ratio = cv2.contourArea(c) / frame_area
                    
                    if len(approx) == 4 and area_ratio > 0.1:
                        # 保存调试结果
                        debug_img = frame.copy()
                        cv2.drawContours(debug_img, [approx], -1, (0, 255, 0), 3)
                        cv2.imwrite(str(self.debug_images_dir / "3_final_region.jpg"), debug_img)
                        
                        bbox = cv2.boundingRect(approx)
                        logger.info(f"   ✅ 在采样点 {point:.0%} 找到 PPT 区域")
                        logger.info(f"      📐 Bounding Box: x={bbox[0]}, y={bbox[1]}, w={bbox[2]}, h={bbox[3]}")
                        logger.info(f"      📊 面积占比: {area_ratio:.1%}")
                        return bbox
            
            logger.error("❌ 所有采样点均未找到有效 PPT 区域")
            return None
            
        finally:
            cap.release()

    def _crop_video_ffmpeg(self, input_path: Path, bbox: tuple) -> Path | None:
        """
        使用 FFmpeg NVENC 硬件加速裁剪视频
        
        核心优势:
            - GPU 解码 + GPU 编码，比 OpenCV CPU 快 5-10 倍
            - 输出质量可控 (CQ 模式)
        
        NVENC 兼容性处理:
            - bbox 宽高必须对齐到偶数 (NVENC 硬性要求)
            - 失败时自动回退到 CPU 裁剪
        
        Args:
            input_path: 输入视频路径
            bbox: 裁剪区域 (x, y, w, h)
            
        Returns:
            Path: 裁剪后视频路径，失败返回 None
        """
        x, y, w, h = bbox
        
        # ========== NVENC 兼容性修正 ==========
        # Why 对齐到偶数?
        #   NVENC 编码器要求输入分辨率为偶数，否则会触发 ACCESS_VIOLATION (0xC0000005)
        # 策略: 向下取偶，确保不出界
        original_bbox = (x, y, w, h)
        
        # ========== NVENC 兼容性修正 ==========
        # Why 对齐到 16?
        #   NVENC 硬件编码器对输入分辨率有 stride (步幅) 要求。
        #   若宽度不是 16 或 32 的倍数，可能导致内存访问越界 (ACCESS_VIOLATION 0xC0000005)。
        #   虽然 yuv420p 只要求偶数，但这在某些驱动版本上不够安全。
        x = (x // 2) * 2
        y = (y // 2) * 2
        w = (w // 16) * 16
        h = (h // 16) * 16
        
        # 安全检查: 防止宽度高度变为 0
        w = max(2, w)
        h = max(2, h)
        
        if (x, y, w, h) != original_bbox:
            logger.debug(f"   🔧 bbox 已修正为偶数: {original_bbox} → ({x}, {y}, {w}, {h})")
        
        output_path = self.cropped_dir / f"{self.output_guid}_cropped.mp4"
        
        # ========== 构造 FFmpeg 命令 ==========
        # 参数说明:
        #   -y: 覆盖已存在的输出文件
        #   -vf crop=w:h:x:y: 裁剪滤镜
        #   -c:v h264_nvenc: 使用 NVIDIA 硬件编码器
        #   -pix_fmt yuv420p: 像素格式，兼容性最佳
        #   -preset p1: 最快预设 (p1=fastest, p7=slowest)
        #   -cq 23: 质量控制，类似 x264 的 CRF (18-28 常用)
        #   -c:a copy: 音频直接复制，不重新编码
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-c:v", "h264_nvenc",
            "-pix_fmt", "yuv420p",
            "-preset", "p1",
            "-cq", "23",
            "-c:a", "copy",
            str(output_path)
        ]
        
        logger.info(f"   🎬 FFmpeg NVENC 硬件加速裁剪中...")
        logger.info(f"      输入: {input_path.name}")
        logger.info(f"      输出: {output_path.name}")
        logger.info(f"      裁剪区域: crop={w}:{h}:{x}:{y}")
        logger.debug(f"   完整命令: {' '.join(cmd)}")
        
        import time
        import re
        ffmpeg_start = time.time()
        
        try:
            # ========== 使用 Popen 实时读取 FFmpeg 进度 ==========
            # Why Popen?
            #   subprocess.run() 是阻塞式的，只能在执行完毕后获取输出。
            #   Popen 允许实时读取 stderr，解析 FFmpeg 的 frame=/time=/speed= 进度信息。
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            
            # FFmpeg 进度信息格式示例:
            # frame=  123 fps= 45 q=28.0 size=    1024kB time=00:00:05.00 bitrate=1677.7kbits/s speed=1.50x
            progress_pattern = re.compile(
                r'frame=\s*(\d+)\s+fps=\s*([\d.]+)\s.*time=(\d+:\d+:\d+\.\d+).*speed=\s*([\d.]+)x'
            )
            
            last_log_time = time.time()
            stderr_lines = []  # 收集所有 stderr 用于错误诊断
            
            logger.info("   📊 FFmpeg 实时进度:")
            
            # 实时读取 stderr (FFmpeg 进度输出在 stderr)
            for line in process.stderr:
                stderr_lines.append(line)
                
                # 解析进度信息
                match = progress_pattern.search(line)
                if match:
                    frame_num = match.group(1)
                    fps = match.group(2)
                    time_pos = match.group(3)
                    speed = match.group(4)
                    
                    # 限制日志频率: 每 2 秒最多打印一次
                    current_time = time.time()
                    if current_time - last_log_time >= 2.0:
                        logger.info(f"      ⏱️ frame={frame_num} fps={fps} time={time_pos} speed={speed}x")
                        last_log_time = current_time
            
            # 等待进程结束
            process.wait()
            
            ffmpeg_time = time.time() - ffmpeg_start
            
            if process.returncode != 0:
                # 只打印 stderr 尾部，避免日志过长
                stderr_text = ''.join(stderr_lines)
                stderr_tail = stderr_text[-500:] if len(stderr_text) > 500 else stderr_text
                logger.error(f"❌ FFmpeg 裁剪失败 (returncode={process.returncode}, 耗时: {ffmpeg_time:.1f}s)")
                logger.error(f"   stderr: {stderr_tail}")
                
                # 回退到 CPU 裁剪
                logger.warning("⚠️ 尝试回退到 CPU 模式...")
                return self._crop_video_cpu_fallback(input_path, bbox)
            
            logger.success(f"✅ FFmpeg NVENC 裁剪完成! 耗时: {ffmpeg_time:.1f}s")
            logger.info(f"      输出文件: {output_path.name}")
            return output_path
            
        except subprocess.TimeoutExpired:
            logger.error("❌ FFmpeg 裁剪超时 (>5分钟)")
            return None
        except FileNotFoundError:
            logger.error("❌ FFmpeg 未安装或不在 PATH 中")
            logger.warning("⚠️ 尝试回退到 CPU 模式...")
            return self._crop_video_cpu_fallback(input_path, bbox)
        except Exception as e:
            logger.exception(f"❌ FFmpeg 裁剪异常: {e}")
            return None

    def _crop_video_cpu_fallback(self, input_path: Path, bbox: tuple) -> Path | None:
        """
        CPU 回退裁剪 (当 FFmpeg NVENC 不可用时)
        
        使用 OpenCV 逐帧裁剪，速度较慢但兼容性好。
        
        Args:
            input_path: 输入视频路径
            bbox: 裁剪区域 (x, y, w, h)
            
        Returns:
            Path: 裁剪后视频路径，失败返回 None
        """
        logger.info("🐌 使用 CPU 模式裁剪视频 (较慢)...")
        
        x, y, w, h = bbox
        output_path = self.cropped_dir / f"{self.output_guid}_cropped.mp4"
        
        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            logger.error(f"❌ 无法打开视频: {input_path}")
            return None
        
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
            
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                cropped = frame[y:y+h, x:x+w]
                writer.write(cropped)
                
                frame_idx += 1
                
                # 每 100 帧更新一次进度
                if frame_idx % 100 == 0:
                    progress = 10 + int((frame_idx / total_frames) * 20)
                    update_task_progress(
                        self.output_guid, 
                        min(30, progress), 
                        f"正在裁剪视频 (CPU): {frame_idx}/{total_frames}"
                    )
                    logger.debug(f"   ✂️ CPU 裁剪进度: {frame_idx}/{total_frames}")
            
            writer.release()
            logger.success(f"✅ CPU 裁剪完成: {output_path.name}")
            return output_path
            
        finally:
            cap.release()

    def _extract_ppt_gpu_pipeline(
        self,
        cropped_video: Path,
        original_video: Path,
        crop_bbox: tuple
    ) -> Path | None:
        """
        三层漏斗 PPT 提取核心流程
        
        关键设计:
            - 使用裁剪视频进行帧分析 (聚焦 PPT 区域，排除干扰)
            - 从原始视频截取最终画面 (保留完整质量和边界)
        
        三层漏斗模型:
            L1 (物理层): GPU 帧差检测 → 场景分割
            L2 (质量层): 拉普拉斯清晰度 → 选冠军帧
            L3 (语义层): OCR 文本去重 → 过滤重复页
        
        Args:
            cropped_video: 裁剪后的视频 (用于帧分析)
            original_video: 原始视频 (用于最终截图)
            crop_bbox: 裁剪区域 (x, y, w, h)
            
        Returns:
            Path: 生成的 PPTX 文件路径，无有效页面时返回 None
        """
        logger.info("🎯 三层漏斗 PPT 提取开始...")
        logger.info("   L1: GPU 帧差检测 → 场景分割")
        logger.info("   L2: 拉普拉斯清晰度 → 选冠军帧")
        logger.info("   L3: OCR 文本去重 → 过滤重复页")
        
        # 创建 PPT 文档
        ppt_path = self.ppt_output_dir / f"{self.output_guid}.pptx"
        prs = Presentation()
        prs.slide_width = Inches(16)
        prs.slide_height = Inches(9)
        
        # 重置 OCR 去重器 (清除上一次任务的缓存)
        self.ocr_deduper.reset()
        
        saved_count = 0
        processed_shots = 0
        
        # ----- 进度回调函数 -----
        def progress_callback(percent: int, message: str) -> None:
            """L1/L2 阶段进度更新 (占 30-70%)"""
            actual_progress = 30 + int(percent * 0.4)
            update_task_progress(self.output_guid, actual_progress, message)
        
        try:
            # ========== L1 + L2: GPU 帧处理 ==========
            logger.info("🔄 L1+L2: 开始 GPU 帧处理...")
            
            for best_shot in self.frame_processor.extract_best_shots(
                cropped_video, 
                progress_callback=progress_callback
            ):
                processed_shots += 1
                
                logger.debug(f"   🎬 候选帧 #{processed_shots}: 帧号={best_shot.frame_index}, "
                            f"清晰度={best_shot.sharpness_score:.4f}")
                
                # ----- 从原始视频读取对应帧 -----
                # Why 用原始视频?
                #   裁剪视频用于分析 (排除干扰)，但最终截图要保留完整画面质量
                original_frame = self.frame_processor.get_frame_at_index(
                    original_video,
                    best_shot.frame_index
                )
                
                if original_frame is None:
                    logger.warning(f"   ⚠️ 无法读取原始帧 {best_shot.frame_index}")
                    continue
                
                # ========== L3: OCR 语义去重 ==========
                update_task_progress(
                    self.output_guid, 
                    70 + int((processed_shots / max(processed_shots, 1)) * 20),
                    f"OCR 去重检查: 第 {processed_shots} 个候选帧"
                )
                
                is_duplicate, text = self.ocr_deduper.is_duplicate(original_frame)
                
                if is_duplicate:
                    logger.debug(f"   🔄 帧 {best_shot.frame_index} 被 OCR 去重丢弃 (文本相似度过高)")
                    continue
                
                # ========== 保存到 PPT ==========
                self._save_frame_to_ppt(original_frame, prs, saved_count)
                saved_count += 1
                
                # 更新 OCR 缓存
                self.ocr_deduper.mark_as_saved(text)
                
                logger.info(f"   📄 保存 PPT 第 {saved_count} 页 (帧 {best_shot.frame_index}, "
                           f"清晰度: {best_shot.sharpness_score:.4f})")
            
            # ========== 保存 PPT ==========
            if saved_count > 0:
                prs.save(str(ppt_path))
                logger.success(f"✅ PPT 生成完毕，共 {saved_count} 页: {ppt_path.name}")
                return ppt_path
            else:
                logger.warning("⚠️ 未提取到任何有效页面，无法生成 PPT")
                return None
        
        finally:
            # ========== GPU 显存清理 (无论成功或异常都会执行) ==========
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("🧹 GPU 显存已清理 (finally block)")

    def _save_frame_to_ppt(self, frame, prs, index: int) -> None:
        """
        将帧保存为 PPT 页面
        
        Args:
            frame: OpenCV BGR 格式的帧数据 (numpy.ndarray)
            prs: python-pptx Presentation 对象
            index: 页面索引 (用于文件命名)
        """
        img_path = self.ppt_images_dir / f"slide_{index:04d}.jpg"
        
        # 保存高质量 JPEG (质量 95%)
        cv2.imwrite(
            str(img_path), 
            frame, 
            [cv2.IMWRITE_JPEG_QUALITY, 95]
        )
        
        # 添加到 PPT (使用空白布局)
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(
            str(img_path),
            Inches(0), 
            Inches(0),
            width=prs.slide_width,
            height=prs.slide_height
        )
