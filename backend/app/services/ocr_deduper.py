"""
文件名: ocr_deduper.py
功能描述: OCR 语义去重模块，实现三层漏斗模型的 L3 语义层
核心逻辑:
    - 使用 PaddleOCR GPU 提取帧中的文字内容
    - 使用 SequenceMatcher (Gestalt 模式匹配) 计算文字相似度
    - 相似度超过阈值则判定为重复页面

设计亮点:
    - PaddleOCR 单例模式，避免重复加载模型 (加载耗时约 3-5 秒)
    - Windows DLL 兼容性修复 (自动加载 zlibwapi.dll)
    - 使用模糊匹配容忍 OCR 识别误差

依赖: paddleocr, paddlepaddle-gpu
"""
import sys
import os
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Tuple

import numpy as np
from loguru import logger


# ============================================================
#              Windows DLL 兼容性修复
# ============================================================
def _fix_paddle_dll_issues() -> None:
    """
    [Windows 特有] 尝试修复 PaddleOCR 依赖的 zlibwapi.dll 缺失问题
    
    PaddleOCR 依赖的 cuDNN 库在 Windows 上通常需要 zlibwapi.dll，
    但该文件不包含在标准安装包中。
    
    策略:
        检测项目根目录下是否存在 libs 文件夹，
        如果存在，将其加入 PATH 和 DLL 搜索路径。
    
    调用时机:
        必须在 import paddleocr 之前调用
    """
    if sys.platform != 'win32':
        return

    # 定位 backend/libs 目录
    # 当前文件: backend/app/services/ocr_deduper.py
    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent.parent  # backend/
    libs_dir = project_root / 'libs'
    
    if libs_dir.exists():
        libs_path = str(libs_dir)
        
        # 1. 加入环境变量 PATH (传统 DLL 加载方式)
        if libs_path not in os.environ.get('PATH', ''):
            os.environ['PATH'] = libs_path + os.pathsep + os.environ['PATH']
            logger.debug(f"📂 已将本地库目录加入 PATH: {libs_path}")
            
        # 2. 加入 Python DLL 搜索路径 (Python 3.8+ 新增)
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(libs_path)
                logger.debug(f"📂 已添加 DLL 搜索目录: {libs_path}")
            except Exception as e:
                logger.warning(f"⚠️ 添加 DLL 目录失败: {e}")


# 在导入 Paddle 前执行修复
_fix_paddle_dll_issues()


# ============================================================
#              PaddleOCR 单例管理
# ============================================================
_ocr_instance = None


def get_ocr_instance():
    """
    获取 PaddleOCR 单例实例
    
    Why 单例模式?
        - PaddleOCR 模型加载耗时约 3-5 秒
        - GPU 显存占用约 1-2GB
        - 全局复用同一实例可显著提升性能
    
    Returns:
        PaddleOCR: 初始化完成的 OCR 实例
        
    Raises:
        ImportError: PaddleOCR 未安装
        Exception: 初始化失败
    """
    global _ocr_instance
    
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            
            # 显式设置 PaddlePaddle 使用 GPU
            import paddle
            if paddle.device.is_compiled_with_cuda():
                paddle.device.set_device('gpu')
                logger.info("🚀 PaddlePaddle 已设置为 GPU 模式")
            else:
                logger.warning("⚠️ PaddlePaddle 未检测到 CUDA，将回退到 CPU")

            logger.info("📦 正在初始化 PaddleOCR (首次加载需 3-5 秒)...")
            
            # 配置说明:
            #   - use_angle_cls=True: 启用文字角度分类，处理倾斜文字
            #   - lang='ch': 中文模型 (支持中英混合)
            # 注意: PaddleOCR 3.x 废弃了 show_log 和 use_gpu 参数
            _ocr_instance = PaddleOCR(
                use_angle_cls=True,
                lang='ch'
            )
            
            logger.success("✅ PaddleOCR 初始化完成")
            
        except ImportError as e:
            logger.error(f"❌ PaddleOCR 导入失败: {e}")
            logger.error("   请运行: pip install paddleocr paddlepaddle-gpu")
            raise
        except Exception as e:
            logger.exception(f"❌ PaddleOCR 初始化异常: {e}")
            raise
    
    return _ocr_instance


# ============================================================
#              OCR 语义去重器
# ============================================================
class OCRDeduper:
    """
    基于 OCR 的语义去重器
    
    三层漏斗模型的 L3 语义层实现。
    
    工作流程:
        1. 对输入帧执行 OCR，提取文本内容
        2. 与上一张已保存页面的文本比对
        3. 使用 SequenceMatcher 计算相似度
        4. 相似度超过阈值则判定为重复页面
    
    Attributes:
        similarity_threshold: 文本相似度阈值 (0-1)
        ocr: PaddleOCR 单例实例
        _last_saved_text: 上一张已保存页面的文本 (用于去重比对)
    
    Example:
        >>> deduper = OCRDeduper(similarity_threshold=0.90)
        >>> is_dup, text = deduper.is_duplicate(frame)
        >>> if not is_dup:
        ...     save_to_ppt(frame)
        ...     deduper.mark_as_saved(text)
    """
    
    def __init__(self, similarity_threshold: float = 0.90) -> None:
        """
        初始化 OCR 去重器
        
        Args:
            similarity_threshold: 文本相似度阈值 (0-1)
                - 超过此阈值视为重复页面
                - 建议值 0.85-0.95
                - 较高值更严格，可能漏判 (保留更多页面)
                - 较低值更宽松，可能误判 (丢弃更多页面)
        """
        self.similarity_threshold = similarity_threshold
        self.ocr = get_ocr_instance()
        
        # 缓存上一张已保存页面的文本
        self._last_saved_text: Optional[str] = None
        
        logger.debug(f"⚙️ OCR 去重器初始化: similarity_threshold={similarity_threshold}")
    
    def extract_text(self, frame: np.ndarray) -> str:
        """
        从图像帧中提取文本
        
        Args:
            frame: OpenCV BGR 格式的图像 (numpy.ndarray)
            
        Returns:
            str: 提取的全部文本，以空格连接
        """
        try:
            # PaddleOCR 返回格式: [[box, (text, confidence)], ...]
            result = self.ocr.ocr(frame, cls=True)
            
            if not result or not result[0]:
                logger.debug("   📝 OCR 未检测到文本")
                return ""
            
            # 提取所有文本并拼接
            texts = []
            for line in result[0]:
                if line and len(line) >= 2:
                    text_info = line[1]
                    if text_info and len(text_info) >= 1:
                        texts.append(text_info[0])
            
            combined_text = " ".join(texts)
            logger.debug(f"   📝 OCR 提取文本: {combined_text[:50]}..." 
                        if len(combined_text) > 50 else f"   📝 OCR 提取文本: {combined_text}")
            return combined_text
            
        except Exception as e:
            logger.warning(f"⚠️ OCR 提取失败: {e}")
            return ""
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两段文本的相似度
        
        使用 Python 内置的 SequenceMatcher (Gestalt 模式匹配)。
        
        Why SequenceMatcher?
            - 对字符替换、插入、删除有较好容忍度
            - 能处理 OCR 识别误差（如 "O" vs "0"、"l" vs "1"）
            - 计算效率高，无需额外依赖
        
        Args:
            text1: 第一段文本
            text2: 第二段文本
            
        Returns:
            float: 相似度分数 (0-1)，越高越相似
        """
        if not text1 or not text2:
            # 如果有一方为空，无法判断相似性
            # 返回 0 表示"不相似"，让调用方决定如何处理
            return 0.0
        
        # 预处理: 去除空白字符，统一小写
        # Why?
        #   - PPT 翻页可能只是标点变化
        #   - 大小写差异不应影响相似度判断
        text1_clean = "".join(text1.lower().split())
        text2_clean = "".join(text2.lower().split())
        
        # SequenceMatcher.ratio() 返回 0-1 的相似度
        similarity = SequenceMatcher(None, text1_clean, text2_clean).ratio()
        return similarity
    
    def is_duplicate(self, frame: np.ndarray) -> Tuple[bool, str]:
        """
        判断当前帧是否与上一张保存的页面重复
        
        核心去重逻辑:
            1. 提取当前帧文本 (PaddleOCR)
            2. 与缓存的上一页文本比对
            3. 相似度超过阈值则判定为重复
        
        Args:
            frame: 当前帧图像 (OpenCV BGR)
            
        Returns:
            Tuple[bool, str]: (是否重复, 当前帧文本)
                - is_duplicate=True: 应丢弃该帧
                - is_duplicate=False: 应保存该帧
        """
        current_text = self.extract_text(frame)
        
        # 首帧无历史对比，直接判定为新页面
        if self._last_saved_text is None:
            self._last_saved_text = current_text
            logger.debug("   🆕 首帧，无历史对比")
            return False, current_text
        
        # 计算与上一保存页的相似度
        similarity = self.calculate_similarity(self._last_saved_text, current_text)
        
        is_dup = similarity > self.similarity_threshold
        
        if is_dup:
            logger.debug(f"   🔄 重复页面检测: 相似度 {similarity:.1%} > {self.similarity_threshold:.0%}")
        else:
            logger.debug(f"   ✨ 新页面检测: 相似度 {similarity:.1%} <= {self.similarity_threshold:.0%}")
            # 更新缓存 (只有保存时才更新)
            self._last_saved_text = current_text
        
        return is_dup, current_text
    
    def mark_as_saved(self, text: str) -> None:
        """
        手动标记某段文本已保存
        
        用于外部调用方控制何时更新"上一页"缓存。
        
        Args:
            text: 已保存页面的文本内容
        """
        self._last_saved_text = text
    
    def reset(self) -> None:
        """
        重置去重器状态
        
        在开始处理新视频前调用，清除上一次任务的缓存。
        """
        self._last_saved_text = None
        logger.debug("🔄 OCR 去重器状态已重置")
