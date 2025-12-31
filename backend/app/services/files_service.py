"""
文件名: files_service.py
功能描述: 文件操作服务，提供安全的文件删除功能
核心逻辑:
    - secure_delete(): 带重试机制的安全删除，解决 Windows 文件锁问题
    
设计亮点:
    - 异步函数，不阻塞事件循环
    - 重试机制应对 Windows PermissionError
    - 支持文件和目录删除
"""
import time
import shutil
import asyncio
from pathlib import Path

from loguru import logger


async def secure_delete(
    path: Path, 
    max_retries: int = 5, 
    delay: float = 0.5
) -> bool:
    """
    安全删除文件或目录，专门解决 Windows 下 PermissionError 问题
    
    Windows 特有问题:
        - 视频处理后文件可能被 FFmpeg/OpenCV 句柄占用
        - 直接删除会抛出 PermissionError
        - 需要等待句柄释放后重试
    
    Args:
        path: 要删除的文件或目录路径
        max_retries: 最大重试次数 (默认 5 次)
        delay: 重试间隔秒数 (默认 0.5 秒)
        
    Returns:
        bool: 删除成功返回 True，失败返回 False
    
    Example:
        >>> await secure_delete(Path("temp/video.mp4"))
        True
    """
    if not path.exists():
        logger.debug(f"⏭️ 文件不存在，跳过删除: {path}")
        return True

    for i in range(max_retries):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            
            logger.debug(f"🗑️ 成功删除: {path}")
            return True
            
        except PermissionError:
            # Windows 特有: 文件被其他进程占用
            logger.warning(f"⚠️ 删除失败 (PermissionError), 重试 {i+1}/{max_retries}: {path.name}")
            await asyncio.sleep(delay)  # 使用异步 sleep 不阻塞事件循环
            
        except Exception as e:
            logger.error(f"❌ 删除出错: {e}")
            break
    
    # 所有重试均失败
    if path.exists():
        logger.error(f"❌ 无法删除文件，已放弃: {path}")
        return False
    
    return True
