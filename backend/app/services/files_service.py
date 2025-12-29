# filename: backend/app/services/files_service.py
import time
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

async def secure_delete(path: Path, max_retries: int = 5, delay: float = 0.5):
    """
    安全删除文件或目录，专门解决 Windows 下 PermissionError 问题。
    
    Args:
        path: 要删除的文件或目录路径
        max_retries: 最大重试次数
        delay: 重试间隔(秒)
    """
    if not path.exists():
        return

    for i in range(max_retries):
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            logger.info(f"成功删除: {path}")
            return
        except PermissionError:
            logger.warning(f"删除失败 (PermissionError), 正在重试 {i+1}/{max_retries}: {path}")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"删除出错: {e}")
            break
    
    # 最后一次尝试（或者记录遗留文件）
    if path.exists():
        logger.error(f"无法删除文件，已放弃: {path}")
