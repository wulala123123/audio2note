"""
文件名: task_manager.py
功能描述: 任务状态管理器，负责维护异步任务的生命周期状态
核心逻辑:
    - 使用内存字典存储任务状态 (生产环境建议替换为 Redis)
    - 提供任务状态的 CRUD 操作
    - 支持进度更新和结果 URL 绑定

任务状态流转:
    pending -> processing -> completed/failed
"""
from typing import Dict, Any, Optional
from enum import Enum

from loguru import logger


class TaskStatus(str, Enum):
    """
    任务状态枚举
    
    流转规则:
        PENDING -> PROCESSING -> COMPLETED
                              -> FAILED
    
    Attributes:
        PENDING: 任务已创建，等待处理资源
        PROCESSING: 正在处理中，前端可轮询 progress
        COMPLETED: 处理完成，result_url 可用
        FAILED: 处理失败，查看 error 字段
    """
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================
#              全局任务存储
# ============================================================
# 生产环境建议替换为 Redis，支持:
#   - 持久化 (服务重启不丢失)
#   - 分布式 (多实例共享状态)
#   - TTL 自动过期 (清理历史任务)
tasks: Dict[str, Dict[str, Any]] = {}


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """
    获取指定任务的当前状态
    
    Args:
        task_id: 任务唯一标识符
        
    Returns:
        dict: 任务状态信息，不存在返回 None
        
        状态字段:
            - status: 任务状态 (pending/processing/completed/failed)
            - progress: 进度百分比 (0-100)
            - message: 当前阶段描述
            - result_url: PPT 下载链接 (完成后)
            - transcript_url: 转录文件链接 (如启用)
            - error: 错误信息 (失败时)
    """
    return tasks.get(task_id)


def init_task(task_id: str) -> None:
    """
    初始化新任务
    
    在接收到上传请求后立即调用，创建初始状态记录。
    
    Args:
        task_id: 任务唯一标识符 (通常为 UUID)
    """
    tasks[task_id] = {
        "status": TaskStatus.PENDING,
        "progress": 0,
        "message": "任务初始化...",
        "result_url": None,
        "error": None
    }
    logger.debug(f"📋 任务创建: {task_id}")


def update_task_progress(
    task_id: str, 
    progress: int, 
    message: str = None, 
    status: TaskStatus = None
) -> None:
    """
    更新任务进度
    
    在处理过程中定期调用，更新进度条和状态消息。
    
    Args:
        task_id: 任务唯一标识符
        progress: 进度百分比 (0-100)
        message: 当前处理阶段描述 (可选)
        status: 任务状态 (可选，默认不修改)
    
    Note:
        如果 task_id 不存在，静默返回不报错
    """
    if task_id not in tasks:
        logger.warning(f"⚠️ 尝试更新不存在的任务: {task_id}")
        return
    
    tasks[task_id]["progress"] = progress
    
    if message:
        tasks[task_id]["message"] = message
    
    if status:
        tasks[task_id]["status"] = status
    else:
        # 自动将 pending 状态转为 processing
        if tasks[task_id]["status"] == TaskStatus.PENDING:
            tasks[task_id]["status"] = TaskStatus.PROCESSING
    
    # 日志: 每 20% 打印一次，避免日志过多
    if progress % 20 == 0 or progress == 100:
        logger.debug(f"📊 任务 {task_id[:8]}... 进度: {progress}% - {message or ''}")


def complete_task(
    task_id: str, 
    result_url: str, 
    transcript_url: str = None
) -> None:
    """
    标记任务为已完成
    
    在所有处理流程结束后调用，绑定结果文件的下载链接。
    
    Args:
        task_id: 任务唯一标识符
        result_url: PPT 文件下载 URL
        transcript_url: 转录文件下载 URL (可选)
    """
    if task_id not in tasks:
        logger.warning(f"⚠️ 尝试完成不存在的任务: {task_id}")
        return
    
    tasks[task_id]["status"] = TaskStatus.COMPLETED
    tasks[task_id]["progress"] = 100
    tasks[task_id]["message"] = "任务完成"
    tasks[task_id]["result_url"] = result_url
    
    if transcript_url:
        tasks[task_id]["transcript_url"] = transcript_url
    
    logger.info(f"✅ 任务完成: {task_id}")
    logger.debug(f"   📄 PPT: {result_url}")
    if transcript_url:
        logger.debug(f"   📝 转录: {transcript_url}")


def fail_task(task_id: str, error_msg: str) -> None:
    """
    标记任务为失败
    
    在处理过程中发生不可恢复错误时调用。
    
    Args:
        task_id: 任务唯一标识符
        error_msg: 错误信息 (将展示给前端)
    """
    if task_id not in tasks:
        logger.warning(f"⚠️ 尝试标记不存在的任务为失败: {task_id}")
        return
    
    tasks[task_id]["status"] = TaskStatus.FAILED
    tasks[task_id]["error"] = error_msg
    tasks[task_id]["message"] = f"任务失败: {error_msg}"
    
    logger.error(f"❌ 任务失败: {task_id}")
    logger.error(f"   原因: {error_msg}")
