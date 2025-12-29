# filename: backend/app/core/task_manager.py
from typing import Dict, Any, Optional
from enum import Enum
import logging

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# 全局内存存储 (生产环境建议使用 Redis)
# key: task_id, value: dict
tasks: Dict[str, Dict[str, Any]] = {}

def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    return tasks.get(task_id)

def init_task(task_id: str):
    tasks[task_id] = {
        "status": TaskStatus.PENDING,
        "progress": 0,
        "message": "任务初始化...",
        "result_url": None,
        "error": None
    }

def update_task_progress(task_id: str, progress: int, message: str = None, status: TaskStatus = None):
    if task_id not in tasks:
        return
    
    tasks[task_id]["progress"] = progress
    if message:
        tasks[task_id]["message"] = message
    if status:
        tasks[task_id]["status"] = status

def complete_task(task_id: str, result_url: str):
    if task_id not in tasks:
        return
    
    tasks[task_id]["status"] = TaskStatus.COMPLETED
    tasks[task_id]["progress"] = 100
    tasks[task_id]["message"] = "任务完成"
    tasks[task_id]["result_url"] = result_url

def fail_task(task_id: str, error_msg: str):
    if task_id not in tasks:
        return
    
    tasks[task_id]["status"] = TaskStatus.FAILED
    tasks[task_id]["error"] = error_msg
    tasks[task_id]["message"] = f"任务失败: {error_msg}"
