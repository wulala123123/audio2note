"""
文件名: gpu_frame_processor.py
功能描述: GPU 加速的视频帧处理模块，实现三层漏斗模型的 L1 物理层 + L2 质量层
核心逻辑:
    - L1 物理层: 使用 PyTorch GPU 计算帧间差异 (MAD 算法)，检测场景切换
    - L2 质量层: 使用 Laplacian Variance 评估每帧清晰度，在场景片段内择优选出"冠军帧"

设计亮点:
    - **Timestamp First**: 所有逻辑基于时间戳 (秒 float)，严禁依赖 frame_index
    - 全程使用 torch.Tensor 在 GPU 上运算，避免 CPU-GPU 数据传输开销
    - 支持 min_scene_duration 过滤动态画面片段
    - Generator 模式流式输出，避免内存占用过高

依赖: torch (CUDA), opencv-python
"""
import cv2
import torch
from pathlib import Path
from dataclasses import dataclass
from typing import Generator, Callable, Optional

from loguru import logger


@dataclass
class BestShot:
    """
    场景片段内的"冠军帧"数据结构 (Timestamp-First 设计)
    
    一个 BestShot 代表一个静止场景中最清晰的那一帧，
    是三层漏斗模型 L1+L2 的输出结果。
    
    核心设计:
        - 以 timestamp (秒) 作为主键锚点
        - frame_index 仅供调试参考，不应用于业务逻辑
    
    Attributes:
        timestamp: 冠军帧的时间戳 (秒，float)，核心锚点
        frame_index: 原始视频中的帧号 (仅调试用)
        sharpness_score: 拉普拉斯清晰度得分 (越高越清晰)
        scene_start_ts: 所属场景的起始时间戳 (秒)
        scene_end_ts: 所属场景的结束时间戳 (秒)
    """
    timestamp: float          # 核心锚点 (秒)
    frame_index: int          # 仅供调试参考
    sharpness_score: float
    scene_start_ts: float     # 场景起始时间 (秒)
    scene_end_ts: float       # 场景结束时间 (秒)


class GPUFrameProcessor:
    """
    GPU 加速的帧处理器
    
    三层漏斗模型的前两层 (L1 物理层 + L2 质量层) 实现。
    
    算法流程:
        1. 按 sample_interval 秒采样视频帧
        2. L1: 实时计算帧间差异 (MAD)
        3. 当差异超过阈值，标记为新场景
        4. L2: 对上一个场景，选出清晰度最高的帧作为"冠军帧"
        5. 场景持续时间不足 min_scene_duration 的，视为"动态片段"丢弃
    
    Attributes:
        diff_threshold: 帧间差异阈值
        min_scene_duration: 场景最短持续时间 (秒)
        sample_interval: 采样间隔 (秒)
        device: 计算设备 (cuda/cpu)
        laplacian_kernel: 预加载到 GPU 的拉普拉斯算子
    
    Example:
        >>> processor = GPUFrameProcessor(diff_threshold=0.12)
        >>> for shot in processor.extract_best_shots(video_path):
        ...     print(f"Timestamp {shot.timestamp:.2f}s, Sharpness: {shot.sharpness_score}")
    """
    
    def __init__(
        self,
        diff_threshold: float = 0.12,
        min_scene_duration: float = 1.5,
        sample_interval: float = 0.2,
        device: str = "cuda"
    ) -> None:
        """
        初始化 GPU 帧处理器
        
        Args:
            diff_threshold: 帧间差异阈值 (0-1)
                - 超过此值视为场景切换
                - 较低值 (0.08-0.12): 对微小变化敏感，适合静态 PPT
                - 较高值 (0.15-0.25): 忽略小幅动画，适合含动效的演示
                
            min_scene_duration: 场景最短持续时间 (秒)
                - 用于过滤动态内容 (如 PPT 中嵌入的视频)
                - 建议值 1.0-2.0 秒
                
            sample_interval: 采样间隔 (秒)
                - 每隔多少秒取一次样
                - 默认 0.2 秒 (每秒 5 个采样点)
                - 较大值节省算力，但可能错过快速翻页
                
            device: 计算设备
                - "cuda": 使用 GPU (推荐)
                - "cpu": 回退到 CPU
        """
        self.diff_threshold = diff_threshold
        self.min_scene_duration = min_scene_duration
        self.sample_interval = sample_interval
        
        # ========== 检查 CUDA 可用性 ==========
        if device == "cuda" and not torch.cuda.is_available():
            logger.warning("⚠️ CUDA 不可用，回退到 CPU 模式")
            self.device = torch.device("cpu")
        else:
            self.device = torch.device(device)
            if device == "cuda":
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"🚀 GPU 帧处理器初始化完成: {gpu_name}")
        
        # ========== 预加载拉普拉斯核到 GPU ==========
        # 标准 3x3 拉普拉斯算子
        # 用于边缘检测，方差越大表示图像越清晰
        self.laplacian_kernel = torch.tensor(
            [[0, 1, 0],
             [1, -4, 1],
             [0, 1, 0]],
            dtype=torch.float32,
            device=self.device
        ).view(1, 1, 3, 3)
        
        logger.debug(f"⚙️ 参数配置: diff_threshold={diff_threshold}, "
                    f"min_scene_duration={min_scene_duration}s, sample_interval={sample_interval}s")
    
    def _frame_to_tensor(self, frame) -> torch.Tensor:
        """
        将 OpenCV BGR 帧转换为 GPU 灰度张量
        
        Why 灰度?
            帧差和清晰度计算都只需要亮度信息，
            转为灰度可减少 3 倍数据传输量和计算量。
        
        Args:
            frame: OpenCV BGR 格式的帧 (numpy.ndarray)
            
        Returns:
            torch.Tensor: 归一化到 [0, 1] 的灰度张量
        """
        # BGR -> Gray (使用 OpenCV，比 torch 更快)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # numpy -> torch，并归一化到 0-1
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
            1. 计算两帧像素级绝对差值
            2. 取均值作为差异分数
            3. 返回 0-1 之间的差异分数
        
        Why MAD 而非 SSIM?
            - MAD 在 GPU 上计算极快 (单次张量运算)
            - 对于场景切换检测，MAD 的敏感度足够
            - SSIM 虽然更精确，但计算复杂度高，不适合实时流处理
        
        Args:
            frame1: 第一帧 (torch.Tensor)
            frame2: 第二帧 (torch.Tensor)
            
        Returns:
            float: 差异分数 (0-1)，越大差异越大
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
        
        Args:
            frame: 输入帧 (torch.Tensor)
            
        Returns:
            float: 清晰度得分 (越高越清晰)
        """
        # 添加 batch 和 channel 维度: (H, W) -> (1, 1, H, W)
        frame_4d = frame.unsqueeze(0).unsqueeze(0)
        
        # GPU 卷积运算
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
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Generator[BestShot, None, None]:
        """
        主入口: 从视频中提取每个场景的"冠军帧" (Timestamp-First)
        
        算法流程:
            1. 按 sample_interval 秒采样视频帧
            2. 实时计算帧间差异 (L1)
            3. 当差异超过阈值，标记为新场景
            4. 对上一个场景，选出清晰度最高的帧 (L2)
            5. 场景持续时间不足 min_scene_duration 的，视为"动态片段"丢弃
        
        关键设计:
            - 所有输出基于时间戳 (秒)，而非帧号
            - 使用 CAP_PROP_POS_MSEC 获取精确时间戳
        
        Args:
            video_path: 输入视频路径
                - 建议传入轻量视频以加速处理
            progress_callback: 进度回调函数
                - 签名: callback(percent: int, message: str)
                - 用于更新任务进度条
            
        Yields:
            BestShot: 每个有效场景的冠军帧信息
        
        Note:
            使用 Generator 模式是为了避免一次性加载所有帧到内存
        """
        video_path = Path(video_path)
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            logger.error(f"❌ 无法打开视频: {video_path}")
            return
        
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            # 计算帧采样间隔 (帧数)
            # Why 保留帧间隔? 因为 OpenCV 需要用 frame index 定位
            frame_sample_interval = max(1, int(fps * self.sample_interval))
            
            logger.info(f"🎬 开始 GPU 帧处理 (Timestamp-First)")
            logger.info(f"   📊 总时长: {duration:.1f}s, FPS: {fps:.1f}")
            logger.info(f"   ⚙️ 采样间隔: {self.sample_interval}s ({frame_sample_interval} 帧)")
            
            # ========== 场景状态机 ==========
            prev_tensor: Optional[torch.Tensor] = None
            scene_start_ts: float = 0.0            # 当前场景起始时间戳
            scene_best_ts: float = 0.0             # 当前场景最清晰帧时间戳
            scene_best_frame_idx: int = 0          # 当前场景最清晰帧索引 (调试用)
            scene_best_sharpness: float = -1.0     # 当前场景最高清晰度
            
            frame_idx = 0                          # 当前读取帧索引
            sampled_count = 0                      # 已采样帧数
            total_scenes = 0                       # 总场景数 (用于日志)
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # ========== 跳帧采样 ==========
                if frame_idx % frame_sample_interval != 0:
                    frame_idx += 1
                    continue
                
                sampled_count += 1
                
                # ========== 获取当前帧时间戳 (秒) ==========
                # Why 使用 CAP_PROP_POS_MSEC?
                #   比 frame_idx / fps 更准确，尤其对于 VFR 视频
                current_ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                
                # 进度回调 (每 10 次采样更新一次)
                if progress_callback and sampled_count % 10 == 0:
                    percent = int((current_ts / duration) * 100) if duration > 0 else 0
                    progress_callback(percent, f"L1+L2 分析: {current_ts:.1f}s / {duration:.1f}s")
                
                # 转换到 GPU 张量
                current_tensor = self._frame_to_tensor(frame)
                
                # 计算当前帧清晰度 (无论是否切换场景都要算，用于择优)
                sharpness = self.compute_laplacian_sharpness(current_tensor)
                
                # ========== 首帧初始化 ==========
                if prev_tensor is None:
                    prev_tensor = current_tensor
                    scene_best_sharpness = sharpness
                    scene_best_ts = current_ts
                    scene_best_frame_idx = frame_idx
                    frame_idx += 1
                    continue
                
                # ========== L1: 计算帧间差异 ==========
                diff = self.compute_frame_difference(prev_tensor, current_tensor)
                
                # ========== 检测场景切换 ==========
                if diff > self.diff_threshold:
                    # 场景结束，检查是否满足最小持续时间
                    scene_duration = current_ts - scene_start_ts
                    
                    if scene_duration >= self.min_scene_duration:
                        # 有效场景，输出冠军帧
                        total_scenes += 1
                        logger.debug(f"   🎯 场景 #{total_scenes} [{scene_start_ts:.2f}s-{current_ts:.2f}s] "
                                   f"冠军帧 @ {scene_best_ts:.2f}s, 清晰度: {scene_best_sharpness:.4f}")
                        
                        yield BestShot(
                            timestamp=scene_best_ts,
                            frame_index=scene_best_frame_idx,
                            sharpness_score=scene_best_sharpness,
                            scene_start_ts=scene_start_ts,
                            scene_end_ts=current_ts
                        )
                    else:
                        # 持续时间不足，丢弃 (可能是动态视频片段)
                        logger.debug(f"   ⏭️ 场景 [{scene_start_ts:.2f}s-{current_ts:.2f}s] 被丢弃: "
                                   f"持续时间 {scene_duration:.2f}s < {self.min_scene_duration}s")
                    
                    # 重置场景状态
                    scene_start_ts = current_ts
                    scene_best_sharpness = sharpness
                    scene_best_ts = current_ts
                    scene_best_frame_idx = frame_idx
                else:
                    # 同一场景内，更新冠军帧 (如果当前帧更清晰)
                    if sharpness > scene_best_sharpness:
                        scene_best_sharpness = sharpness
                        scene_best_ts = current_ts
                        scene_best_frame_idx = frame_idx
                
                prev_tensor = current_tensor
                frame_idx += 1
            
            # ========== 处理最后一个场景 ==========
            final_ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            scene_duration = final_ts - scene_start_ts if final_ts > scene_start_ts else duration - scene_start_ts
            
            if scene_duration >= self.min_scene_duration:
                total_scenes += 1
                logger.debug(f"   🎯 最后场景 #{total_scenes} [{scene_start_ts:.2f}s-{final_ts:.2f}s] "
                           f"冠军帧 @ {scene_best_ts:.2f}s, 清晰度: {scene_best_sharpness:.4f}")
                
                yield BestShot(
                    timestamp=scene_best_ts,
                    frame_index=scene_best_frame_idx,
                    sharpness_score=scene_best_sharpness,
                    scene_start_ts=scene_start_ts,
                    scene_end_ts=final_ts
                )
            
            logger.success(f"✅ GPU 帧处理完成，共检测到 {total_scenes} 个有效场景")
                
        finally:
            cap.release()
            # 清理 GPU 缓存
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
                logger.debug("🧹 GPU 显存已清理")
    
    def get_frame_at_timestamp(self, video_path: Path, timestamp: float):
        """
        工具方法: 从视频中读取指定时间戳的帧
        
        用于在确定冠军帧时间戳后，从原始视频中截取实际画面。
        
        Args:
            video_path: 视频路径
            timestamp: 目标时间戳 (秒)
            
        Returns:
            numpy.ndarray: BGR 格式的帧数据，失败返回 None
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning(f"⚠️ 无法打开视频: {video_path}")
            return None
        
        try:
            # 使用毫秒定位 (比帧号定位更精确)
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()
    
    # ========== 兼容性方法 (deprecated) ==========
    def get_frame_at_index(self, video_path: Path, frame_index: int):
        """
        [DEPRECATED] 使用 get_frame_at_timestamp() 代替
        
        保留此方法仅为向后兼容，新代码应使用时间戳版本。
        
        Args:
            video_path: 视频路径
            frame_index: 帧索引号 (0-indexed)
            
        Returns:
            numpy.ndarray: BGR 格式的帧数据，失败返回 None
        """
        logger.warning("⚠️ get_frame_at_index() 已废弃，请使用 get_frame_at_timestamp()")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning(f"⚠️ 无法打开视频: {video_path}")
            return None
        
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()
