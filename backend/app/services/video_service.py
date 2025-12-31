# filename: backend/app/services/video_service.py
"""
视频处理服务 - GPU 加速版

全链路架构:
1. FFmpeg NVENC 硬件加速裁剪
2. 三层漏斗模型 PPT 提取:
   - L1 物理层: GPU 帧差检测
   - L2 质量层: 拉普拉斯清晰度择优
   - L3 语义层: OCR 文本去重

设计亮点:
- 裁剪视频用于帧分析 (聚焦 PPT 区域)
- 从原始视频截取最终画面 (保留完整质量)
"""
import cv2
import shutil
import subprocess
import logging
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from app.core.config import OUTPUT_DIR, TEMP_DIR
from app.core.task_manager import update_task_progress
from app.services.audio_service import get_audio_transcriber
from app.services.gpu_frame_processor import GPUFrameProcessor, BestShot
from app.services.ocr_deduper import OCRDeduper

logger = logging.getLogger(__name__)


class VideoService:
    """
    视频处理服务主类
    
    职责: 编排整个视频 -> PPT 转换流程
    """
    
    def __init__(self, output_guid: str):
        self.output_guid = output_guid
        self.base_output_path = OUTPUT_DIR / output_guid
        
        # 定义子目录
        self.cropped_dir = self.base_output_path / "cropped_video"
        self.debug_images_dir = self.base_output_path / "debug_images"
        self.ppt_images_dir = self.base_output_path / "ppt_images"
        self.ppt_output_dir = self.base_output_path / "ppt_output"
        self.transcripts_dir = self.base_output_path / "transcripts"
        
        # 创建所需文件夹
        for p in [self.cropped_dir, self.debug_images_dir, 
                  self.ppt_images_dir, self.ppt_output_dir, self.transcripts_dir]:
            p.mkdir(parents=True, exist_ok=True)
        
        # 初始化 GPU 处理器
        self.frame_processor = GPUFrameProcessor(
            diff_threshold=0.12,      # 帧差阈值
            min_scene_duration=1.5,   # 最小场景持续时间 (秒)
            sample_fps=4              # 每秒采样 4 帧
        )
        
        # 初始化 OCR 去重器
        self.ocr_deduper = OCRDeduper(
            similarity_threshold=0.90  # 90% 文本相似度阈值
        )

    def process(
        self, 
        input_video_path: Path, 
        enable_ppt_extraction: bool = True,
        enable_audio_transcription: bool = False
    ) -> dict:
        """
        全流程处理：[可选] PPT 提取 + [可选] 音频转录
        
        两个功能模块完全独立，可自由组合。
        
        Args:
            input_video_path: 原始视频路径
            enable_ppt_extraction: 是否启用 PPT 提取
            enable_audio_transcription: 是否启用音频转录
            
        Returns:
            dict: 处理结果，包含各输出文件路径
        """
        input_video_path = Path(input_video_path)
        logger.info(f"开始处理视频, GUID: {self.output_guid}, "
                   f"PPT提取: {enable_ppt_extraction}, 音频转录: {enable_audio_transcription}")
        
        ppt_path = None
        transcript_path = None
        
        # ========== 模块 1: PPT 提取 (条件执行) ==========
        if enable_ppt_extraction:
            # 进度区间: 0% - 85% (若同时启用音频) 或 0% - 100% (仅 PPT)
            ppt_progress_end = 85 if enable_audio_transcription else 100
            
            # 1.1 定位 PPT 区域
            update_task_progress(self.output_guid, 5, "正在定位 PPT 区域...")
            bbox = self._locate_ppt_region(input_video_path)
            
            if not bbox:
                raise ValueError("无法定位 PPT 区域，请确保视频中包含清晰的 PPT 画面")
            
            # 1.2 FFmpeg 硬件加速裁剪
            update_task_progress(self.output_guid, 10, "正在裁剪视频 (GPU 加速)...")
            cropped_video_path = self._crop_video_ffmpeg(input_video_path, bbox)
            
            if not cropped_video_path:
                raise ValueError("视频裁剪失败")
            
            # 1.3 三层漏斗提取 PPT
            ppt_path = self._extract_ppt_gpu_pipeline(
                cropped_video=cropped_video_path,
                original_video=input_video_path,
                crop_bbox=bbox
            )
            
            logger.info(f"PPT 提取完成: {ppt_path}")
        
        # ========== 模块 2: 音频转录 (条件执行，完全独立) ==========
        if enable_audio_transcription:
            # 进度区间: 85% - 100% (若同时启用 PPT) 或 0% - 100% (仅音频)
            audio_progress_start = 85 if enable_ppt_extraction else 0
            
            update_task_progress(
                self.output_guid, 
                audio_progress_start + 5, 
                "正在进行语音识别 (FunASR)..."
            )
            
            try:
                transcript_text = get_audio_transcriber().transcribe_video(input_video_path)
                
                if transcript_text:
                    transcript_path = self.transcripts_dir / f"{self.output_guid}.txt"
                    with open(transcript_path, "w", encoding="utf-8") as f:
                        f.write(transcript_text)
                    logger.info(f"字幕生成成功: {transcript_path}")
                else:
                    logger.warning("字幕生成返回为空")
            except Exception as e:
                logger.error(f"字幕生成过程出错: {e}")
        
        # 返回结果
        return {
            "guid": self.output_guid,
            "cropped_video": str(self.cropped_dir / f"{self.output_guid}_cropped.mp4") if enable_ppt_extraction else None,
            "ppt_file": str(ppt_path) if ppt_path else None,
            "transcript_file": str(transcript_path) if transcript_path else None
        }

    def _locate_ppt_region(self, video_path: Path) -> tuple | None:
        """
        定位视频中的 PPT 区域 (边缘检测法)
        
        策略:
        - 在视频 20%/40%/60% 位置各采样一帧
        - 使用 Canny 边缘检测 + 轮廓分析
        - 返回最大四边形区域的 bounding box
        
        Returns:
            tuple: (x, y, w, h) 或 None
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.error(f"无法打开视频: {video_path}")
            return None
        
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            sample_points = [0.2, 0.4, 0.6]
            
            for point in sample_points:
                frame_idx = int(total_frames * point)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                
                if not ret:
                    continue
                
                # 保存调试图像
                cv2.imwrite(str(self.debug_images_dir / "0_original.jpg"), frame)
                
                # 边缘检测
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                cv2.imwrite(str(self.debug_images_dir / "1_gray.jpg"), gray)
                
                blurred = cv2.GaussianBlur(gray, (5, 5), 0)
                edged = cv2.Canny(blurred, 30, 120)
                cv2.imwrite(str(self.debug_images_dir / "2_edged.jpg"), edged)
                
                # 轮廓分析
                contours, _ = cv2.findContours(
                    edged.copy(), 
                    cv2.RETR_EXTERNAL, 
                    cv2.CHAIN_APPROX_SIMPLE
                )
                
                if not contours:
                    continue
                
                # 取最大的 5 个轮廓
                contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
                
                for c in contours:
                    peri = cv2.arcLength(c, True)
                    approx = cv2.approxPolyDP(c, 0.03 * peri, True)
                    
                    # 筛选: 4 边形 + 面积占比 > 10%
                    area_ratio = cv2.contourArea(c) / (frame.shape[0] * frame.shape[1])
                    if len(approx) == 4 and area_ratio > 0.1:
                        # 保存调试结果
                        debug_img = frame.copy()
                        cv2.drawContours(debug_img, [approx], -1, (0, 255, 0), 3)
                        cv2.imwrite(str(self.debug_images_dir / "3_final_region.jpg"), debug_img)
                        
                        bbox = cv2.boundingRect(approx)
                        logger.info(f"PPT 区域定位成功 (采样点 {point:.0%}): {bbox}")
                        return bbox
            
            logger.error("所有采样点均未找到有效 PPT 区域")
            return None
            
        finally:
            cap.release()

    def _crop_video_ffmpeg(self, input_path: Path, bbox: tuple) -> Path | None:
        """
        使用 FFmpeg NVENC 硬件加速裁剪视频
        
        核心优势:
        - GPU 解码 + GPU 编码，比 OpenCV CPU 快 5-10 倍
        - 输出质量可控 (CRF 模式)
        
        Args:
            input_path: 输入视频路径
            bbox: 裁剪区域 (x, y, w, h)
            
        Returns:
            Path: 裁剪后视频路径，失败返回 None
        """
        x, y, w, h = bbox
        
        # 修正: NVENC 要求输入宽高必须为偶数 (且最好 2 对齐)
        # 否则会报 Access Violation 0xC0000005
        # 策略: 向下取偶，确保不出界
        x = x if x % 2 == 0 else x - 1
        y = y if y % 2 == 0 else y - 1
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1
        
        # 安全检查: 防止宽度高度变为 0
        w = max(2, w)
        h = max(2, h)
        
        output_path = self.cropped_dir / f"{self.output_guid}_cropped.mp4"
        
        # FFmpeg 命令构造
        # 
        # Why 使用 libx264 而非 h264_nvenc?
        # - FFmpeg CUDA/NVENC 在不同环境下兼容性问题频发 (ACCESS_VIOLATION 0xC0000005)
        # - libx264 是最稳定可靠的软件编码器，跨环境表现一致
        # - 对于 30 分钟 720p 视频，CPU 编码约需 1-2 分钟，完全可接受
        # - 如需恢复 GPU 加速，可将 libx264 改为 h264_nvenc，-crf 改为 -cq
        # 
        # UPDATE 2025-12-31: 修复了 bbox 奇数导致的 crash，恢复尝试 h264_nvenc
        cmd = [
            "ffmpeg",
            "-y",  # 覆盖输出文件
            "-i", str(input_path),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-c:v", "h264_nvenc",
            "-pix_fmt", "yuv420p", # 显式指定像素格式，防止格式协商错误
            "-preset", "p1",  # NVENC 最快预设 (p1=fastest, p7=slowest)
            "-cq", "23",  # 质量控制 (18-28 常用)
            "-c:a", "copy",  # 音频直接复制
            str(output_path)
        ]
        
        logger.info(f"执行 FFmpeg 裁剪: {' '.join(cmd)}")
        
        try:
            # Why encoding='utf-8' + errors='replace'?
            # Windows 中文系统默认使用 GBK 编码读取 subprocess 输出，
            # 但 FFmpeg 输出包含 UTF-8 字符，会导致 UnicodeDecodeError。
            # 显式指定 UTF-8 并用 replace 容错，避免解码异常。
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=300  # 5 分钟超时
            )
            
            if result.returncode != 0:
                # 只打印 stderr 的最后 1000 字符（包含实际错误），避免日志过长
                stderr_tail = result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr
                logger.error(f"FFmpeg 裁剪失败 (returncode={result.returncode})")
                logger.error(f"FFmpeg stderr (尾部): {stderr_tail}")
                # 回退到 CPU 裁剪
                logger.warning("尝试回退到 CPU 模式...")
                return self._crop_video_cpu_fallback(input_path, bbox)
            
            logger.info(f"FFmpeg 裁剪完成: {output_path}")
            return output_path
            
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg 裁剪超时")
            return None
        except FileNotFoundError:
            logger.error("FFmpeg 未安装或不在 PATH 中")
            return self._crop_video_cpu_fallback(input_path, bbox)
        except Exception as e:
            logger.error(f"FFmpeg 裁剪异常: {e}")
            return None

    def _crop_video_cpu_fallback(self, input_path: Path, bbox: tuple) -> Path | None:
        """
        CPU 回退裁剪 (当 FFmpeg NVENC 不可用时)
        
        使用 OpenCV 逐帧裁剪，速度较慢但兼容性好
        """
        x, y, w, h = bbox
        output_path = self.cropped_dir / f"{self.output_guid}_cropped.mp4"
        
        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
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
                if frame_idx % 100 == 0:
                    progress = 10 + int((frame_idx / total_frames) * 20)
                    update_task_progress(
                        self.output_guid, 
                        min(30, progress), 
                        f"正在裁剪视频 (CPU): {frame_idx}/{total_frames}"
                    )
            
            writer.release()
            logger.info(f"CPU 裁剪完成: {output_path}")
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
        
        Args:
            cropped_video: 裁剪后的视频 (用于分析)
            original_video: 原始视频 (用于截图)
            crop_bbox: 裁剪区域 (x, y, w, h)
            
        Returns:
            Path: 生成的 PPTX 文件路径
        """
        logger.info("开始 GPU 三层漏斗 PPT 提取...")
        
        # 创建 PPT
        ppt_path = self.ppt_output_dir / f"{self.output_guid}.pptx"
        prs = Presentation()
        prs.slide_width = Inches(16)
        prs.slide_height = Inches(9)
        
        # 重置 OCR 去重器
        self.ocr_deduper.reset()
        
        saved_count = 0
        processed_shots = 0
        
        # 进度回调
        def progress_callback(percent, message):
            # L1/L2 占 30-70% 进度
            actual_progress = 30 + int(percent * 0.4)
            update_task_progress(self.output_guid, actual_progress, message)
        
        # L1 + L2: GPU 帧处理，获取每个场景的冠军帧
        for best_shot in self.frame_processor.extract_best_shots(
            cropped_video, 
            progress_callback=progress_callback
        ):
            processed_shots += 1
            
            # 从【原始视频】读取对应帧 (保留完整画面)
            original_frame = self.frame_processor.get_frame_at_index(
                original_video,
                best_shot.frame_index
            )
            
            if original_frame is None:
                logger.warning(f"无法读取原始帧 {best_shot.frame_index}")
                continue
            
            # L3: OCR 语义去重
            update_task_progress(
                self.output_guid, 
                70 + int((processed_shots / max(processed_shots, 1)) * 20),
                f"OCR 去重检查: 第 {processed_shots} 个候选帧"
            )
            
            is_duplicate, text = self.ocr_deduper.is_duplicate(original_frame)
            
            if is_duplicate:
                logger.info(f"帧 {best_shot.frame_index} 被 OCR 去重丢弃")
                continue
            
            # 保存到 PPT
            self._save_frame_to_ppt(original_frame, prs, saved_count)
            saved_count += 1
            
            # 更新 OCR 缓存 (标记为已保存)
            self.ocr_deduper.mark_as_saved(text)
            
            logger.info(f"保存 PPT 第 {saved_count} 页 (帧 {best_shot.frame_index}, "
                       f"清晰度: {best_shot.sharpness_score:.4f})")
        
        # 清理 GPU 显存
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.debug("GPU 显存已清理")
        
        # 保存 PPT
        if saved_count > 0:
            prs.save(str(ppt_path))
            logger.info(f"PPT 生成完毕，共 {saved_count} 页: {ppt_path}")
            return ppt_path
        else:
            logger.warning("未提取到任何有效页面，无法生成 PPT")
            return None

    def _save_frame_to_ppt(self, frame, prs, index: int):
        """
        将帧保存为 PPT 页面
        
        Args:
            frame: OpenCV BGR 帧数据
            prs: python-pptx Presentation 对象
            index: 页面索引 (用于命名)
        """
        img_path = self.ppt_images_dir / f"slide_{index:04d}.jpg"
        
        # 保存高质量 JPEG
        cv2.imwrite(
            str(img_path), 
            frame, 
            [cv2.IMWRITE_JPEG_QUALITY, 95]
        )
        
        # 添加到 PPT
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白布局
        slide.shapes.add_picture(
            str(img_path),
            Inches(0), 
            Inches(0),
            width=prs.slide_width,
            height=prs.slide_height
        )
