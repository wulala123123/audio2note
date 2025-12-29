# filename: backend/app/services/video_service.py
import cv2
import shutil
import logging
from pathlib import Path
from skimage.metrics import structural_similarity as ssim
from pptx import Presentation
from pptx.util import Inches

# config
from app.core.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

class VideoService:
    def __init__(self, output_guid: str):
        self.output_guid = output_guid
        self.base_output_path = OUTPUT_DIR / output_guid
        
        # 定义子目录
        self.cropped_dir = self.base_output_path / "cropped_video"
        self.debug_images_dir = self.base_output_path / "debug_images"
        self.ppt_images_dir = self.base_output_path / "ppt_images"
        self.ppt_output_dir = self.base_output_path / "ppt_output" # 存放最终 PPTX
        
        # 创建所需文件夹
        for p in [self.cropped_dir, self.debug_images_dir, self.ppt_images_dir, self.ppt_output_dir]:
            p.mkdir(parents=True, exist_ok=True)

    def process(self, input_video_path: Path) -> dict:
        """
        全流程处理：裁剪 -> 提取PPT
        """
        logger.info(f"开始处理视频流程, GUID: {self.output_guid}")
        
        # 1. 裁剪
        cropped_video_path = self._crop_video(input_video_path)
        if not cropped_video_path:
            raise ValueError("视频裁剪失败，无法定位 PPT 区域")

        # 2. 提取并生成 PPT
        ppt_path = self._extract_frames_and_create_ppt(cropped_video_path)
        
        # 返回结果路径 (相对于 backend 根目录 或 绝对路径，这里返回绝对路径)
        return {
            "guid": self.output_guid,
            "cropped_video": str(cropped_video_path),
            "ppt_file": str(ppt_path) if ppt_path else None
        }

    def _locate_ppt_region(self, frame, debug_dir: Path):
        """
        在单帧中定位PPT区域 (原 crop_ppt.py 逻辑)
        """
        # 保存原始帧
        cv2.imwrite(str(debug_dir / "0_original.jpg"), frame)

        # 灰度
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cv2.imwrite(str(debug_dir / "1_gray.jpg"), gray)
        
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 120)
        cv2.imwrite(str(debug_dir / "2_edged.jpg"), edged)

        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None

        # 筛选
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
        for c in contours:
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.03 * peri, True)

            # 假设 PPT 是最大的 4 边形且面积占比足够
            if len(approx) == 4 and cv2.contourArea(c) > frame.shape[0] * frame.shape[1] * 0.1:
                # 画出最终结果用于调试
                debug_img = frame.copy()
                cv2.drawContours(debug_img, [approx], -1, (0, 255, 0), 3)
                cv2.imwrite(str(debug_dir / "3_final_region.jpg"), debug_img)
                return cv2.boundingRect(approx)
        
        return None

    def _crop_video(self, input_path: Path) -> Path | None:
        """
        裁剪视频核心逻辑
        """
        input_path = Path(input_path)
        logger.info(f"正在裁剪视频: {input_path}")

        cap = cv2.VideoCapture(str(input_path))
        if not cap.isOpened():
            logger.error(f"无法打开视频: {input_path}")
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        # 尝试定位 PPT
        bbox = None
        sample_points = [0.2, 0.4, 0.6] # 采样点
        for point in sample_points:
            frame_idx = int(total_frames * point)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret: 
                continue
            
            bbox = self._locate_ppt_region(frame, self.debug_images_dir)
            if bbox:
                logger.info(f"在 {point:.0%} 处成功定位 PPT")
                break
        
        if not bbox:
            logger.error("自动定位 PPT 失败")
            cap.release()
            return None

        x, y, w, h = bbox
        output_path = self.cropped_dir / f"{self.output_guid}_cropped.mp4"
        
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

        # 重置并裁剪
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        # 简化版进度打印
        frame_cursor = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            cropped = frame[y:y+h, x:x+w]
            writer.write(cropped)
            frame_cursor += 1
            if frame_cursor % 500 == 0:
                logger.info(f"已裁剪 {frame_cursor}/{total_frames} 帧")

        cap.release()
        writer.release()
        logger.info(f"视频裁剪完成: {output_path}")
        return output_path

    def _extract_frames_and_create_ppt(self, video_path: Path) -> Path | None:
        """
        提取关键帧并生成 PPT (原 extract_ppt.py 逻辑)
        """
        logger.info(f"开始提取 PPT 关键帧: {video_path}")
        
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None

        ppt_path = self.ppt_output_dir / f"{self.output_guid}.pptx"
        prs = Presentation()
        prs.slide_width = Inches(16)
        prs.slide_height = Inches(9)

        ssim_threshold = 0.95
        frame_interval = 20 # 降低检测频率提高速度
        stability_frames = 3
        stability_threshold = 0.995

        last_saved_gray = None
        current_frame_idx = -1
        candidate_frame = None
        stable_counter = 0
        saved_count = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            current_frame_idx += 1

            # 跳帧检测
            if current_frame_idx > 0 and current_frame_idx % frame_interval != 0:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 第一帧必选
            if last_saved_gray is None:
                self._save_frame_to_ppt(frame, prs, saved_count)
                last_saved_gray = gray
                saved_count += 1
                continue

            # SSIM 比较
            score, _ = ssim(last_saved_gray, gray, full=True)
            
            # 如果差异大 (score < threshold) -> 是新页面候选
            if score < ssim_threshold:
                if candidate_frame is None:
                    candidate_frame = frame.copy()
                    stable_counter = 1
                else:
                    # 检查候选帧是否稳定
                    candidate_gray = cv2.cvtColor(candidate_frame, cv2.COLOR_BGR2GRAY)
                    cand_score, _ = ssim(candidate_gray, gray, full=True)
                    
                    if cand_score > stability_threshold:
                        stable_counter += 1
                    else:
                        # 不稳定，更新候选
                        candidate_frame = frame.copy()
                        stable_counter = 1
            else:
                # 与上一张已保存的相似 -> 重置候选
                if candidate_frame is not None:
                    candidate_frame = None
                    stable_counter = 0
            
            # 如果候选帧稳定达到阈值 -> 保存
            if candidate_frame is not None and stable_counter >= stability_frames:
                self._save_frame_to_ppt(candidate_frame, prs, saved_count)
                last_saved_gray = cv2.cvtColor(candidate_frame, cv2.COLOR_BGR2GRAY)
                saved_count += 1
                candidate_frame = None
                stable_counter = 0

        cap.release()
        
        if saved_count > 0:
            prs.save(str(ppt_path))
            logger.info(f"PPT 生成完毕: {ppt_path}")
            return ppt_path
        else:
            logger.warning("未提取到关键帧，无法生成 PPT")
            return None

    def _save_frame_to_ppt(self, frame, prs, index):
        img_path = self.ppt_images_dir / f"slide_{index:04d}.jpg"
        cv2.imwrite(str(img_path), frame)
        
        slide = prs.slides.add_slide(prs.slide_layouts[6]) # 空白布局
        slide.shapes.add_picture(str(img_path), Inches(0), Inches(0), width=prs.slide_width, height=prs.slide_height)
