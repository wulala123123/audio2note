"""
文件名: audio_service.py
功能描述: 音频转录服务，实现本地语音识别 + 云端纠错的混合方案
核心逻辑:
    - AudioTranscriber 类 (单例模式): 管理 FunASR 模型生命周期
    - transcribe_video(): 主流程 - 提取音频 -> FunASR 本地推理 -> Gemini 云端纠错
    - init_audio_service(): 应用启动时预加载模型

技术栈:
    - 音频提取: moviepy
    - 本地推理: FunASR (CUDA GPU 加速)
    - 云端纠错: Google Gemini 2.5 Flash
"""
import os
import uuid
import time
from pathlib import Path

from moviepy import VideoFileClip
from dotenv import load_dotenv
from google import genai
from funasr import AutoModel
from loguru import logger

# 加载环境变量 (GEMINI_API_KEY)
load_dotenv()


class AudioTranscriber:
    """
    音频转录服务类 (单例模式)
    
    职责:
        1. 管理本地 FunASR 模型 (只加载一次)
        2. 执行 "本地转录 + 云端纠错" 混合流程
    
    Why 单例模式?
        - FunASR 模型加载耗时约 10-30 秒
        - GPU 显存占用约 2-4GB
        - 全局复用同一实例可避免重复加载
    
    Attributes:
        _instance: 单例实例引用
        _model: FunASR 模型实例 (类变量，全局共享)
    
    Example:
        >>> # 应用启动时
        >>> init_audio_service()
        >>> 
        >>> # 处理视频时
        >>> transcriber = get_audio_transcriber()
        >>> text = transcriber.transcribe_video(Path("lecture.mp4"))
    """
    _instance = None
    _model = None

    def __new__(cls):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super(AudioTranscriber, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """
        初始化音频转录服务
        
        Note:
            由于单例模式，__init__ 可能被多次调用，
            使用 _initialized 标志确保只初始化一次。
        """
        if not hasattr(self, '_initialized'):
            self._load_model()
            self._setup_gemini()
            self._initialized = True

    def _load_model(self) -> None:
        """
        初始化加载 FunASR 模型
        
        Warning:
            这是一个耗时操作 (10-30秒)，且会占用 GPU 显存 (2-4GB)。
            首次运行会自动从 ModelScope 下载模型权重 (约 1-2GB)。
        """
        if AudioTranscriber._model is not None:
            logger.info("ℹ️ FunASR 模型已加载，跳过初始化")
            return

        logger.info("=" * 50)
        logger.info("📦 正在加载 FunASR 模型...")
        logger.info("   ⚠️ 首次运行会自动下载权重 (约 1-2GB)")
        logger.info("=" * 50)
        
        try:
            # ----- FunASR 模型配置 -----
            # 模型来源: ModelScope (阿里达摩院)
            # 模型能力: 中文语音识别 + VAD + 标点恢复 + 说话人分离
            model_config = {
                # 主 ASR 模型: SeACo-Paraformer (16kHz 中文)
                "model": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
                "model_revision": "v2.0.4",
                
                # VAD 模型: 语音活动检测 (识别静音片段)
                "vad_model": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                "vad_model_revision": "v2.0.4",
                
                # 标点恢复模型: 自动添加标点符号
                "punc_model": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
                "punc_model_revision": "v2.0.4",
                
                # 说话人分离模型 (可选，用于多人对话场景)
                "spk_model": "iic/speech_campplus_sv_zh-cn_16k-common",
                "spk_model_revision": "v2.0.2",
            }
            
            # 加载模型到 GPU
            # disable_update=True: 禁用模型自动更新检查，加快启动速度
            AudioTranscriber._model = AutoModel(
                **model_config, 
                device="cuda",
                disable_update=True
            )
            
            logger.success("✅ FunASR 模型加载成功 (CUDA)")
            
        except Exception as e:
            logger.exception(f"❌ 模型加载失败: {e}")
            raise RuntimeError(f"无法加载音频模型: {e}")

    def _setup_gemini(self) -> None:
        """
        配置 Gemini API
        
        检查 GEMINI_API_KEY 环境变量是否存在。
        如果未配置，云端纠错功能将不可用，但不影响本地转录。
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("⚠️ 未检测到 GEMINI_API_KEY 环境变量")
            logger.warning("   云端纠错功能将不可用，转录结果可能包含错别字")
        else:
            logger.debug("🔑 Gemini API Key 已配置")

    def transcribe_video(self, video_path: Path) -> str:
        """
        视频转录主流程
        
        流程:
            1. 提取音频: 使用 moviepy 从视频中提取 16kHz 单声道 WAV
            2. 本地推理: 使用 FunASR 进行 GPU 加速的语音识别
            3. 云端纠错: 使用 Gemini 修正错别字和标点 (可选)
        
        Args:
            video_path: 输入视频文件路径
            
        Returns:
            str: 转录文本 (经 Gemini 纠错，或原始识别结果)
        
        Raises:
            FileNotFoundError: 视频文件不存在
            Exception: 转录过程中发生错误
        
        Warning:
            此方法包含 GPU 推理和网络请求，极度耗时 (数分钟)。
            上层调用者必须确保在 ThreadPool 中运行:
            await run_in_threadpool(transcriber.transcribe_video, video_path)
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        logger.info("=" * 50)
        logger.info(f"🎤 开始转录视频: {video_path.name}")
        logger.info("=" * 50)
        
        temp_audio_path = None
        try:
            # ========== Step 1: 提取音频 ==========
            logger.info("📤 Step 1: 从视频提取音频...")
            temp_audio_path = video_path.parent / f"{uuid.uuid4().hex}_temp.wav"
            
            # 使用 moviepy 提取音频
            # 转换为 16000Hz 单声道 (FunASR 最佳输入格式)
            video_clip = VideoFileClip(str(video_path))
            
            if video_clip.audio is None:
                logger.warning("⚠️ 该视频没有音频轨道")
                video_clip.close()
                return ""
            
            audio_start = time.time()
            video_clip.audio.write_audiofile(
                str(temp_audio_path), 
                fps=16000,           # 采样率 16kHz
                nbytes=2,            # 16-bit
                codec='pcm_s16le',   # PCM 编码
                ffmpeg_params=["-ac", "1"],  # 单声道
                logger=None          # 静默输出
            )
            video_clip.close()
            
            logger.success(f"   ✅ 音频提取完成，耗时: {time.time() - audio_start:.1f}s")
            logger.debug(f"   📂 临时文件: {temp_audio_path}")

            # ========== Step 2: 本地推理 (FunASR) ==========
            logger.info("🧠 Step 2: FunASR 本地推理...")
            inference_start = time.time()
            
            # batch_size_s=300 表示每次处理 300 秒音频
            # Why 300秒? 对于 30 分钟以上的长视频，分批处理避免显存溢出
            res = AudioTranscriber._model.generate(
                input=str(temp_audio_path), 
                batch_size_s=300, 
                hotword='Video2Note'  # 热词增强
            )
            
            # 提取纯文本结果
            # res 结构: [{'text': '...', 'timestamp': [...]}]
            raw_text = ""
            if isinstance(res, list) and len(res) > 0:
                raw_text = "".join([item.get('text', '') for item in res])
            
            inference_time = time.time() - inference_start
            logger.success(f"   ✅ 本地推理完成，耗时: {inference_time:.1f}s")
            logger.debug(f"   📝 原始识别结果 (前100字): {raw_text[:100]}...")

            if not raw_text.strip():
                logger.warning("⚠️ 本地识别结果为空")
                return ""

            # ========== Step 3: 云端纠错 (Gemini) ==========
            corrected_text = self._correct_text_with_gemini(raw_text)
            
            logger.info("=" * 50)
            logger.success("✅ 视频转录完成")
            logger.info("=" * 50)
            
            return corrected_text

        except Exception as e:
            logger.exception(f"❌ 转录流程发生错误: {e}")
            raise
        finally:
            # ========== Cleanup: 删除临时音频 ==========
            if temp_audio_path and temp_audio_path.exists():
                try:
                    os.remove(temp_audio_path)
                    logger.debug(f"🗑️ 已清理临时音频文件: {temp_audio_path.name}")
                except Exception as e:
                    logger.warning(f"⚠️ 清理临时文件失败: {e}")

    def _correct_text_with_gemini(self, raw_text: str) -> str:
        """
        调用 Gemini 修正错别字和标点
        
        如果 API 调用失败，直接降级返回原始文本。
        
        Args:
            raw_text: FunASR 原始识别文本
            
        Returns:
            str: 纠错后的文本，或原始文本 (如果纠错失败)
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.debug("⏭️ 跳过 Gemini 纠错 (未配置 API Key)")
            return raw_text

        logger.info("☁️ Step 3: Gemini 云端纠错...")
        gemini_start = time.time()
        
        try:
            # 使用新版 google-genai SDK
            client = genai.Client(api_key=api_key)
            
            # 纠错 Prompt
            # 关键要求:
            #   - 只修正错别字和标点，不改变原意
            #   - 不进行总结或摘要
            #   - 直接输出全文
            prompt = (
                "你是一个专业的会议记录员。请阅读以下机器识别的文本，"
                "修正其中的同音错别字、标点错误和语句不通顺的地方。"
                "保持原意，不要进行总结或摘要，直接输出修正后的全文：\n\n"
                f"{raw_text}"
            )
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            
            if response.text:
                logger.success(f"   ✅ Gemini 纠错完成，耗时: {time.time() - gemini_start:.1f}s")
                return response.text.strip()
            else:
                logger.warning("⚠️ Gemini 返回内容为空，使用原始文本")
                return raw_text

        except Exception as e:
            logger.error(f"❌ Gemini 纠错调用失败: {e}")
            logger.warning("⚠️ 将返回原始识别文本")
            return raw_text


# ============================================================
#              全局服务管理
# ============================================================
global_audio_transcriber = None


def init_audio_service() -> None:
    """
    初始化全局音频服务实例
    
    在应用启动时调用 (main.py 的 lifespan 中)。
    预加载 FunASR 模型，避免首次请求时的延迟。
    """
    global global_audio_transcriber
    if global_audio_transcriber is None:
        logger.info("🔧 初始化音频服务 (预加载模型)...")
        global_audio_transcriber = AudioTranscriber()
        logger.success("✅ 音频服务初始化完成")


def get_audio_transcriber() -> AudioTranscriber:
    """
    获取全局音频服务实例
    
    Returns:
        AudioTranscriber: 初始化完成的转录服务实例
        
    Raises:
        RuntimeError: 服务未初始化 (未调用 init_audio_service)
    """
    if global_audio_transcriber is None:
        raise RuntimeError(
            "Audio Service 未初始化。请先调用 init_audio_service()"
        )
    return global_audio_transcriber
