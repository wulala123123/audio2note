# filename: backend/app/services/gpu_frame_processor.py
"""
GPU 加速的视频帧处理模块 (L1 物理层 + L2 质量层)

核心职责:
- L1: 使用 PyTorch GPU 计算帧间差异，检测场景切换
- L2: 使用 Laplacian Variance 评估每帧清晰度，在场景片段内择优

设计亮点:
- 全程使用 torch.Tensor 在 GPU 上运算，避免 CPU-GPU 数据传输开销
- 支持 min_scene_duration 过滤持续动态画面（如嵌入视频片段）

依赖: torch (CUDA), opencv-python
"""
import cv2
import torch
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class BestShot:
    """
    场景片段内的"冠军帧"数据结构
    
    Attributes:
        frame_index: 原始视频中的帧号 (0-indexed)
        sharpness_score: 拉普拉斯清晰度得分
        scene_start: 所属场景的起始帧号
        scene_end: 所属场景的结束帧号
    """
    frame_index: int
    sharpness_score: float
    scene_start: int
    scene_end: int


class GPUFrameProcessor:
    """
    GPU 加速的帧处理器
    
    三层漏斗模型的前两层 (L1 物理层 + L2 质量层) 实现
    """
    
    def __init__(
        self,
        diff_threshold: float = 0.12,
        min_scene_duration: float = 1.5,
        sample_fps: int = 4,
        device: str = "cuda"
    ):
        """
        初始化 GPU 帧处理器
        
        Args:
            diff_threshold: 帧间差异阈值 (0-1)，超过此值视为场景切换
                           - 较低值 (0.08-0.12): 对微小变化敏感，适合静态 PPT
                           - 较高值 (0.15-0.25): 忽略小幅动画，适合含动效的演示
            min_scene_duration: 场景最短持续时间 (秒)
                               用于过滤持续动态内容 (如嵌入视频)
            sample_fps: 采样帧率 (每秒取多少帧)
                       较低值节省算力，但可能错过快速翻页
            device: 计算设备 ("cuda" 或 "cpu")
        """
        self.diff_threshold = diff_threshold
        self.min_scene_duration = min_scene_duration
        self.sample_fps = sample_fps
        
        # 检查 CUDA 可用性
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA 不可用，回退到 CPU 模式")
            self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)
            if device == "cuda":
                logger.info(f"GPU 帧处理器初始化完成: {torch.cuda.get_device_name(0)}")
        
        # Laplacian 核 (用于清晰度计算) - 预加载到 GPU
        # 标准 3x3 拉普拉斯算子
        self.laplacian_kernel = torch.tensor(
            [[0, 1, 0],
             [1, -4, 1],
             [0, 1, 0]],
            dtype=torch.float32,
            device=self.device
        ).view(1, 1, 3, 3)
    
    def _frame_to_tensor(self, frame) -> torch.Tensor:
        """
        将 OpenCV BGR 帧转换为 GPU 灰度张量
        
        Why 灰度? 帧差和清晰度计算都只需要亮度信息，
        转为灰度可减少 3 倍数据传输量
        """
        # BGR -> Gray (OpenCV 格式)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # numpy -> torch, 并归一化到 0-1
        tensor = torch.from_numpy(gray).float().to(self.device) / 255.0
        return tensor
    
    def compute_frame_difference(
        self,
        frame1: torch.Tensor,
        frame2: torch.Tensor
    ) -> float:
        """
        L1 物理层核心: 计算两帧之间的差异度
        
        使用 Mean Absolute Difference (MAD) 算法:
        - 计算两帧像素级绝对差值的均值
        - 返回 0-1 之间的差异分数
        
        Why MAD 而非 SSIM?
        - MAD 在 GPU 上计算极快 (单次张量运算)
        - 对于场景切换检测，MAD 的敏感度足够
        - SSIM 虽然更精确，但计算复杂度高，不适合实时流处理
        """
        diff = torch.abs(frame1 - frame2).mean().item()
        return diff
    
    def compute_laplacian_sharpness(self, frame: torch.Tensor) -> float:
        """
        L2 质量层核心: 计算帧的清晰度得分 (Laplacian Variance)
        
        原理:
        1. 使用拉普拉斯算子对图像进行卷积 (检测边缘)
        2. 计算卷积结果的方差
        3. 方差越大，说明边缘越锐利，图像越清晰
        
        Why Laplacian Variance?
        - 对焦距/模糊变化非常敏感
        - 能有效区分清晰帧和运动模糊帧
        - 计算简单，适合 GPU 并行
        """
        # 添加 batch 和 channel 维度: (H, W) -> (1, 1, H, W)
        frame_4d = frame.unsqueeze(0).unsqueeze(0)
        
        # GPU 卷积
        laplacian = torch.nn.functional.conv2d(
            frame_4d,
            self.laplacian_kernel,
            padding=1
        )
        
        # 返回方差作为清晰度得分
        variance = laplacian.var().item()
        return variance
    
    def extract_best_shots(
        self,
        video_path: Path,
        progress_callback=None
    ) -> Generator[BestShot, None, None]:
        """
        主入口: 从视频中提取每个场景的"冠军帧"
        
        算法流程:
        1. 按 sample_fps 采样视频帧
        2. 实时计算帧间差异 (L1)
        3. 当差异超过阈值，标记为新场景
        4. 对上一个场景，选出清晰度最高的帧 (L2)
        5. 场景持续时间不足 min_scene_duration 的，视为"动态片段"丢弃
        
        Args:
            video_path: 输入视频路径 (建议使用裁剪后的版本以聚焦 PPT 区域)
            progress_callback: 进度回调函数 (percent, message)
            
        Yields:
            BestShot: 每个有效场景的冠军帧信息
        """
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            logger.error(f"无法打开视频: {video_path}")
            return
        
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # 计算采样间隔 (每隔多少帧取一次样)
            sample_interval = max(1, int(fps / self.sample_fps))
            # 场景最小帧数阈值
            min_scene_frames = int(self.min_scene_duration * self.sample_fps)
            
            logger.info(f"开始帧处理: 总帧数={total_frames}, FPS={fps:.1f}, "
                       f"采样间隔={sample_interval}, 最小场景帧数={min_scene_frames}")
            
            # 场景状态机
            prev_tensor = None
            scene_start = 0
            scene_best_frame_idx = 0
            scene_best_sharpness = -1.0
            frame_idx = 0
            sampled_count = 0
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 跳帧采样
                if frame_idx % sample_interval != 0:
                    frame_idx += 1
                    continue
                
                sampled_count += 1
                
                # 进度回调
                if progress_callback and frame_idx % (sample_interval * 10) == 0:
                    percent = int((frame_idx / total_frames) * 100)
                    progress_callback(percent, f"分析帧: {frame_idx}/{total_frames}")
                
                # 转换到 GPU 张量
                current_tensor = self._frame_to_tensor(frame)
                
                # 计算当前帧清晰度 (无论是否切换场景都要算，用于择优)
                sharpness = self.compute_laplacian_sharpness(current_tensor)
                
                # 首帧初始化
                if prev_tensor is None:
                    prev_tensor = current_tensor
                    scene_best_sharpness = sharpness
                    scene_best_frame_idx = frame_idx
                    frame_idx += 1
                    continue
                
                # L1: 计算帧间差异
                diff = self.compute_frame_difference(prev_tensor, current_tensor)
                
                # 检测场景切换
                if diff > self.diff_threshold:
                    # 场景结束，检查是否满足最小持续时间
                    scene_sampled_frames = sampled_count - 1  # 当前帧属于新场景
                    
                    if scene_sampled_frames >= min_scene_frames:
                        # 有效场景，输出冠军帧
                        yield BestShot(
                            frame_index=scene_best_frame_idx,
                            sharpness_score=scene_best_sharpness,
                            scene_start=scene_start,
                            scene_end=frame_idx - sample_interval
                        )
                        logger.debug(f"场景 [{scene_start}-{frame_idx}] 冠军帧: "
                                    f"{scene_best_frame_idx}, 清晰度: {scene_best_sharpness:.4f}")
                    else:
                        # 持续时间不足，丢弃 (可能是动态视频片段)
                        logger.debug(f"场景 [{scene_start}-{frame_idx}] 被丢弃: "
                                    f"持续帧数 {scene_sampled_frames} < {min_scene_frames}")
                    
                    # 重置场景状态
                    scene_start = frame_idx
                    scene_best_sharpness = sharpness
                    scene_best_frame_idx = frame_idx
                    sampled_count = 1
                else:
                    # 同一场景内，更新冠军帧 (如果当前帧更清晰)
                    if sharpness > scene_best_sharpness:
                        scene_best_sharpness = sharpness
                        scene_best_frame_idx = frame_idx
                
                prev_tensor = current_tensor
                frame_idx += 1
            
            # 处理最后一个场景
            if sampled_count >= min_scene_frames:
                yield BestShot(
                    frame_index=scene_best_frame_idx,
                    sharpness_score=scene_best_sharpness,
                    scene_start=scene_start,
                    scene_end=frame_idx - 1
                )
                logger.debug(f"最后场景 [{scene_start}-{frame_idx}] 冠军帧: "
                            f"{scene_best_frame_idx}, 清晰度: {scene_best_sharpness:.4f}")
                
        finally:
            cap.release()
            # 清理 GPU 缓存
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
                logger.debug("GPU 显存已清理")
    
    def get_frame_at_index(self, video_path: Path, frame_index: int):
        """
        工具方法: 从视频中读取指定帧
        
        用于在确定冠军帧索引后，从原始视频中截取实际画面
        
        Args:
            video_path: 视频路径 (应使用原始未裁剪视频以获取完整画面)
            frame_index: 帧索引号 (0-indexed)
            
        Returns:
            numpy.ndarray: BGR 格式的帧数据，失败返回 None
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()
