"""
数据模型定义
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class ScheduleType(Enum):
    """调度类型枚举"""
    INTERVAL = "INTERVAL"   # 间隔调度（秒、分、小时）
    CRON = "CRON"           # Cron 表达式调度


class TaskStatus(Enum):
    """任务状态枚举"""
    IDLE = "IDLE"           # 空闲状态
    QUEUED = "QUEUED"       # 已加入队列，等待执行
    RUNNING = "RUNNING"     # 正在执行
    ERROR = "ERROR"         # 执行出错


class SyncTask:
    """同步任务数据模型"""
    
    def __init__(
        self,
        name: str,
        source_path: str,
        target_path: str,
        interval: int = 300,  # 默认 5 分钟
        schedule_type: str = "INTERVAL",
        cron_expression: Optional[str] = None,
        task_id: Optional[str] = None,
        status: str = "IDLE",
        last_run_time: Optional[str] = None,
        enabled: bool = True,
        overwrite_existing: bool = False,  # 是否覆盖已存在的文件，默认跳过
        thread_count: int = 1,  # 同步线程数，默认1（单线程）
        rule_not_exists: bool = False,  # 子规则：文件不存在时同步
        rule_size_diff: bool = False,  # 子规则：大小不一致时同步
        rule_mtime_newer: bool = False,  # 子规则：源文件更新时同步
        is_slow_storage: bool = False,  # 目标是否为慢速存储（NAS/网盘挂载）
        size_min_bytes: Optional[int] = None,  # 最小文件大小（字节），None 表示不限制
        size_max_bytes: Optional[int] = None,  # 最大文件大小（字节），None 表示不限制
        suffix_mode: str = "NONE",  # 后缀过滤模式：NONE/INCLUDE/EXCLUDE
        suffix_list: Optional[list[str]] = None  # 后缀列表，小写且不带点，如 ["mp4", "mkv"]
    ):
        """
        初始化同步任务
        
        Args:
            name: 任务名称
            source_path: 源目录路径
            target_path: 目标目录路径
            interval: 同步间隔（秒），当 schedule_type=INTERVAL 时有效
            schedule_type: 调度类型（INTERVAL 或 CRON）
            cron_expression: Cron 表达式，当 schedule_type=CRON 时使用
            task_id: 任务唯一标识符（UUID），不提供则自动生成
            status: 任务状态
            last_run_time: 上次运行时间（ISO格式字符串）
            enabled: 是否启用任务
            overwrite_existing: 是否覆盖已存在的文件（True=覆盖，False=跳过）
            thread_count: 同步线程数（1=单线程，>1=多线程）
            rule_not_exists: 子规则 - 目标不存在时同步
            rule_size_diff: 子规则 - 大小不一致时同步
            rule_mtime_newer: 子规则 - 源文件更新时同步
            is_slow_storage: 目标是否为慢速存储（NAS/网盘挂载）
            size_min_bytes: 最小文件大小（字节），None 表示不限制
            size_max_bytes: 最大文件大小（字节），None 表示不限制
            suffix_mode: 后缀过滤模式：NONE（默认）/INCLUDE/EXCLUDE
            suffix_list: 后缀列表（字符串数组），例如 ["mp4", "mkv"]
        """
        self.id = task_id if task_id else str(uuid.uuid4())
        self.name = name
        self.source_path = source_path
        self.target_path = target_path
        self.interval = interval
        self.schedule_type = ScheduleType[schedule_type] if isinstance(schedule_type, str) else schedule_type
        self.cron_expression = cron_expression
        self.status = TaskStatus[status] if isinstance(status, str) else status
        self.last_run_time = last_run_time
        self.enabled = enabled
        self.recursive = True  # 固定为递归模式
        self.overwrite_existing = overwrite_existing
        self.is_slow_storage = is_slow_storage
        # 根据存储类型自动调整线程数
        if is_slow_storage:
            self.thread_count = min(max(1, thread_count), 2)  # 慢速存储限制最多2线程
        else:
            self.thread_count = max(1, thread_count)  # 确保至少1个线程
        self.rule_not_exists = rule_not_exists
        self.rule_size_diff = rule_size_diff
        self.rule_mtime_newer = rule_mtime_newer
        self.size_min_bytes = size_min_bytes
        self.size_max_bytes = size_max_bytes
        # 规范化后缀过滤配置
        self.suffix_mode = (suffix_mode or "NONE").upper()
        self.suffix_list = [s.lower().lstrip(".") for s in suffix_list] if suffix_list else None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将任务对象转换为字典，用于 JSON 序列化
        
        Returns:
            包含任务所有字段的字典
        """
        return {
            "id": self.id,
            "name": self.name,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "interval": self.interval,
            "schedule_type": self.schedule_type.value,
            "cron_expression": self.cron_expression,
            "status": self.status.value,
            "last_run_time": self.last_run_time,
            "enabled": self.enabled,
            "recursive": self.recursive,
            "overwrite_existing": self.overwrite_existing,
            "thread_count": self.thread_count,
            "rule_not_exists": self.rule_not_exists,
            "rule_size_diff": self.rule_size_diff,
            "rule_mtime_newer": self.rule_mtime_newer,
            "is_slow_storage": self.is_slow_storage,
            "size_min_bytes": self.size_min_bytes,
            "size_max_bytes": self.size_max_bytes,
            "suffix_mode": self.suffix_mode,
            "suffix_list": self.suffix_list
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SyncTask':
        """
        从字典创建任务对象，用于 JSON 反序列化
        
        Args:
            data: 包含任务字段的字典
            
        Returns:
            SyncTask 实例
        """
        return cls(
            task_id=data.get("id"),
            name=data["name"],
            source_path=data["source_path"],
            target_path=data["target_path"],
            interval=data.get("interval", 300),
            schedule_type=data.get("schedule_type", "INTERVAL"),
            cron_expression=data.get("cron_expression"),
            status=data.get("status", "IDLE"),
            last_run_time=data.get("last_run_time"),
            enabled=data.get("enabled", True),
            overwrite_existing=data.get("overwrite_existing", False),
            thread_count=data.get("thread_count", 1),
            rule_not_exists=data.get("rule_not_exists", False),
            rule_size_diff=data.get("rule_size_diff", False),
            rule_mtime_newer=data.get("rule_mtime_newer", False),
            is_slow_storage=data.get("is_slow_storage", False),
            size_min_bytes=data.get("size_min_bytes"),
            size_max_bytes=data.get("size_max_bytes"),
            suffix_mode=data.get("suffix_mode", "NONE"),
            suffix_list=data.get("suffix_list")
        )
    
    def update_status(self, new_status: TaskStatus):
        """
        更新任务状态
        
        Args:
            new_status: 新的任务状态
        """
        self.status = new_status
    
    def update_last_run_time(self):
        """更新上次运行时间为当前时间"""
        self.last_run_time = datetime.now().isoformat()
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"SyncTask(id={self.id}, name={self.name}, "
            f"status={self.status.value}, interval={self.interval}s)"
        )
    
    def __str__(self) -> str:
        """用户友好的字符串表示"""
        return f"[{self.status.value}] {self.name} ({self.interval}s)"
