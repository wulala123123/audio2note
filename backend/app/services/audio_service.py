# filename: backend/app/services/audio_service.py
import os
import logging
import uuid
from pathlib import Path
import time
from moviepy import VideoFileClip
from dotenv import load_dotenv
from google import genai
from funasr import AutoModel

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger(__name__)

class AudioTranscriber:
    """
    音频转录服务类 (单例模式)
    负责:
    1. 管理本地 FunASR 模型 (只加载一次)
    2. 执行 "本地转录 + 云端纠错" 流程
    """
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AudioTranscriber, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # 确保只初始化一次
        if not hasattr(self, '_initialized'):
            self._load_model()
            self._setup_gemini()
            self._initialized = True

    def _load_model(self):
        """
        初始化加载 FunASR 模型。
        注意: 这是一个耗时操作，且会占用显存。
        """
        if AudioTranscriber._model is not None:
            logger.info("FunASR 模型已加载，跳过初始化。")
            return

        logger.info("正在加载 FunASR 模型 (首次运行会自动下载权重)...")
        try:
            # 严格按照用户指定的模型配置
            model_config = {
                "model": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
                "model_revision": "v2.0.4",
                "vad_model": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                "vad_model_revision": "v2.0.4",
                "punc_model": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
                "punc_model_revision": "v2.0.4",
                "spk_model": "iic/speech_campplus_sv_zh-cn_16k-common",
                "spk_model_revision": "v2.0.2",
            }
            
            # 加载模型到 GPU (device="cuda")
            AudioTranscriber._model = AutoModel(**model_config, device="cuda",disable_update=True)
            logger.info("✅ FunASR 模型加载成功 (CUDA)。")
        except Exception as e:
            logger.error(f"❌ 模型加载失败: {e}")
            raise RuntimeError(f"无法加载音频模型: {e}")

    def _setup_gemini(self):
        """配置 Gemini API"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("⚠ 未检测到 GEMINI_API_KEY，云端纠错功能将不可用！")
        else:
            # 新版 google-genai SDK 使用 Client 实例，无需全局 configure
            pass

    def transcribe_video(self, video_path: Path) -> str:
        """
        核心流程:
        1. 提取音频 (wav 16k)
        2. 本地 FunASR 推理 -> raw_text
        3. Gemini 纠错 -> corrected_text (失败则返回 raw_text)
        
        注意!!!!
        此方法包含 GPU 推理和网络请求，极度耗时 (数分钟)。
        上层调用者 (video_service) 必须确保在 ThreadPool 中运行此方法:
        await run_in_threadpool(audio_service.transcribe_video, video_path)
        """
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        temp_audio_path = None
        try:
            # --- Step 1: 提取音频 ---
            logger.info(f"正在从视频提取音频: {video_path.name}")
            temp_audio_path = video_path.parent / f"{uuid.uuid4().hex}_temp.wav"
            
            # 使用 moviepy 提取音频, 转换为 16000Hz 单声道 (FunASR 最佳格式)
            video_clip = VideoFileClip(str(video_path))
            if video_clip.audio is None:
                logger.warning("该视频没有音频轨道。")
                return ""
                
            video_clip.audio.write_audiofile(
                str(temp_audio_path), 
                fps=16000, 
                nbytes=2, 
                codec='pcm_s16le', 
                ffmpeg_params=["-ac", "1"],
                logger=None  # 静默输出，moviepy v2.x 已移除 verbose 参数
            )
            video_clip.close()

            # --- Step 2: 本地推理 (FunASR) ---
            logger.info("开始本地 FunASR 推理...")
            inference_start = time.time()
            
            # batch_size_s=300 表示每次处理 300秒音频，长音频必备
            res = AudioTranscriber._model.generate(
                input=str(temp_audio_path), 
                batch_size_s=300, 
                hotword='Video2Note' # 可选热词
            )
            
            # 提取纯文本结果
            # res 结构通常是List[Dict], 例如 [{'text': '...'}]
            raw_text = ""
            if isinstance(res, list) and len(res) > 0:
                raw_text = "".join([item.get('text', '') for item in res])
            
            logger.info(f"本地推理完成，耗时: {time.time() - inference_start:.2f}s")
            logger.debug(f"原始识别结果 (前100字): {raw_text[:100]}...")

            if not raw_text.strip():
                logger.warning("本地识别结果为空。")
                return ""

            # --- Step 3: 云端纠错 (Gemini) ---
            corrected_text = self._correct_text_with_gemini(raw_text)
            return corrected_text

        except Exception as e:
            logger.error(f"转录流程发生错误: {e}")
            # 出错时返回空字符串或抛出，视业务需求定。这里抛出以便上层捕获
            raise e
        finally:
            # --- Cleanup: 删除临时音频 ---
            if temp_audio_path and temp_audio_path.exists():
                try:
                    os.remove(temp_audio_path)
                    logger.info("已清理临时音频文件。")
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {e}")

    def _correct_text_with_gemini(self, raw_text: str) -> str:
        """
        调用 Gemini 修正错别字和标点。
        如果调用失败，直接降级返回原始文本。
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return raw_text

        logger.info("正在调用 Gemini 进行文本纠错...")
        try:
            # 使用新版 SDK Client
            client = genai.Client(api_key=api_key)
            
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
                logger.info("Gemini 纠错完成。")
                return response.text.strip()
            else:
                logger.warning("Gemini 返回内容为空，使用原始文本。")
                return raw_text

        except Exception as e:
            logger.error(f"Gemini 纠错调用失败: {e}，将返回原始文本。")
            return raw_text

# 全局单例实例，供外部导入使用
# 全局实例 (默认 None, 需通过 init_audio_service 初始化)
global_audio_transcriber = None

def init_audio_service():
    """在应用启动时调用，初始化全局音频服务实例"""
    global global_audio_transcriber
    if global_audio_transcriber is None:
        logger.info("Initializing Audio Service (Loading Models)...")
        global_audio_transcriber = AudioTranscriber()
        logger.info("Audio Service Initialized.")

def get_audio_transcriber() -> AudioTranscriber:
    """获取全局音频服务实例"""
    if global_audio_transcriber is None:
        raise RuntimeError("Audio Service has not been initialized. Please call init_audio_service() first.")
    return global_audio_transcriber
