"""
任务调度管理器
使用 APScheduler 进行定时调度，通过队列解耦调度和执行
"""

import json
import queue
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.models import SyncTask, TaskStatus
from core.worker import FileSyncer


class TaskScheduler:
    """任务调度管理器"""
    
    def __init__(self, config_path: str = "config/tasks.json"):
        """
        初始化调度器
        
        Args:
            config_path: 任务配置文件路径
        """
        self.config_path = Path(config_path)
        self.tasks: Dict[str, SyncTask] = {}  # task_id -> SyncTask
        self.task_queue = queue.Queue()  # 任务执行队列
        self.scheduler = BackgroundScheduler()  # APScheduler 后台调度器
        self.consumer_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.log_callback: Optional[Callable[[str], None]] = None
        self.progress_callback: Optional[Callable[[str, int, int, str], None]] = None
        
        # 确保配置目录存在
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 加载已保存的任务
        self.load_tasks()
    
    def set_log_callback(self, callback: Callable[[str], None]):
        """
        设置日志回调函数
        
        Args:
            callback: 日志回调函数
        """
        self.log_callback = callback

    def set_progress_callback(self, callback: Callable[[str, int, int, str], None]):
        """
        设置进度回调函数

        Args:
            callback: 进度回调函数
        """
        self.progress_callback = callback
    
    def _log(self, message: str):
        """
        输出日志

        Args:
            message: 日志消息
        """
        if self.log_callback:
            self.log_callback(message)
    
    def add_task(self, task: SyncTask) -> bool:
        """
        添加任务到调度器
        
        Args:
            task: 同步任务对象
            
        Returns:
            是否添加成功
        """
        try:
            if task.id in self.tasks:
                self._log(f"任务已存在: {task.name} ({task.id})")
                return False
            
            # 添加到任务字典
            self.tasks[task.id] = task
            
            # 如果任务启用且调度器已运行，则添加定时任务
            if task.enabled and self.is_running:
                self._schedule_task(task)
            
            # 保存配置
            self.save_tasks()
            
            self._log(f"✓ 任务已添加: {task.name} (每 {task.interval} 秒)")
            return True
            
        except Exception as e:
            self._log(f"✗ 添加任务失败: {task.name} - {str(e)}")
            return False
    
    def remove_task(self, task_id: str) -> bool:
        """
        移除任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否移除成功
        """
        try:
            if task_id not in self.tasks:
                self._log(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            
            # 从调度器中移除
            if self.scheduler.get_job(task_id):
                self.scheduler.remove_job(task_id)
            
            # 从任务字典中移除
            del self.tasks[task_id]
            
            # 保存配置
            self.save_tasks()
            
            self._log(f"✓ 任务已移除: {task.name}")
            return True
            
        except Exception as e:
            self._log(f"✗ 移除任务失败: {task_id} - {str(e)}")
            return False
    
    def update_task(self, task_id: str, **kwargs) -> bool:
        """
        更新任务配置
        
        Args:
            task_id: 任务ID
            **kwargs: 要更新的字段
            
        Returns:
            是否更新成功
        """
        try:
            if task_id not in self.tasks:
                self._log(f"任务不存在: {task_id}")
                return False
            
            task = self.tasks[task_id]
            old_interval = task.interval
            old_enabled = task.enabled
            
            # 更新字段
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            
            # 如果间隔或启用状态改变，重新调度
            if (task.interval != old_interval or task.enabled != old_enabled) and self.is_running:
                if self.scheduler.get_job(task_id):
                    self.scheduler.remove_job(task_id)
                
                if task.enabled:
                    self._schedule_task(task)
            
            # 保存配置
            self.save_tasks()
            
            self._log(f"✓ 任务已更新: {task.name}")
            return True
            
        except Exception as e:
            self._log(f"✗ 更新任务失败: {task_id} - {str(e)}")
            return False
    
    def get_task(self, task_id: str) -> Optional[SyncTask]:
        """
        获取任务对象
        
        Args:
            task_id: 任务ID
            
        Returns:
            任务对象，不存在则返回 None
        """
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[SyncTask]:
        """
        获取所有任务列表
        
        Returns:
            任务列表
        """
        return list(self.tasks.values())
    
    def _schedule_task(self, task: SyncTask):
        """
        将任务添加到 APScheduler
        
        Args:
            task: 同步任务对象
        """
        trigger = IntervalTrigger(seconds=task.interval)
        self.scheduler.add_job(
            func=self._on_task_triggered,
            trigger=trigger,
            id=task.id,
            args=[task.id],
            replace_existing=True
        )
        self._log(f"任务已调度: {task.name} (间隔: {task.interval}s)")
    
    def _on_task_triggered(self, task_id: str):
        """
        定时器触发回调：将任务加入队列
        
        Args:
            task_id: 任务ID
        """
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        
        # 检查任务状态，避免重复入队
        if task.status == TaskStatus.IDLE:
            # 更新状态为 QUEUED
            task.update_status(TaskStatus.QUEUED)
            
            # 将任务ID放入队列
            self.task_queue.put(task_id)
            
            self._log(f"⏱ 任务已加入队列: {task.name}")
        else:
            self._log(f"⚠ 任务仍在执行中，跳过本次调度: {task.name} (状态: {task.status.value})")
    
    def _task_consumer(self):
        """
        后台消费者线程：从队列取出任务并执行同步
        """
        self._log("📌 任务消费者线程已启动")
        
        while self.is_running:
            try:
                # 从队列取出任务ID（超时1秒，避免阻塞关闭）
                try:
                    task_id = self.task_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 获取任务对象
                if task_id not in self.tasks:
                    self._log(f"⚠ 任务不存在，跳过: {task_id}")
                    self.task_queue.task_done()
                    continue
                
                task = self.tasks[task_id]
                
                # 更新状态为 RUNNING
                task.update_status(TaskStatus.RUNNING)
                self._log(f"▶ 开始执行任务: {task.name}")
                
                # 执行同步
                try:
                    syncer = FileSyncer(
                        source_dir=task.source_path,
                        target_dir=task.target_path
                    )

                    def report_progress(done: int, total: int, filename: str):
                        if self.progress_callback:
                            self.progress_callback(task.id, done, total, filename)

                    def task_log(message: str):
                        self._log(f"{task.id}|{message}")

                    stats = syncer.sync_directory(
                        recursive=task.recursive,
                        verify_md5=task.verify_md5,
                        log_callback=task_log,
                        progress_callback=report_progress
                    )
                    
                    # 更新状态为 IDLE
                    task.update_status(TaskStatus.IDLE)
                    task.update_last_run_time()
                    
                    self._log(
                        f"✓ 任务执行完成: {task.name} "
                        f"(成功: {stats['success']}, "
                        f"失败: {stats['failed']})"
                    )
                    
                except Exception as e:
                    # 更新状态为 ERROR
                    task.update_status(TaskStatus.ERROR)
                    self._log(f"✗ 任务执行失败: {task.name} - {str(e)}")
                
                finally:
                    # 标记任务完成
                    self.task_queue.task_done()
                    
                    # 保存任务状态
                    self.save_tasks()
                
            except Exception as e:
                self._log(f"消费者线程异常: {str(e)}")
                time.sleep(1)
        
        self._log("📌 任务消费者线程已停止")
    
    def start(self):
        """启动调度器和消费者线程"""
        if self.is_running:
            self._log("⚠ 调度器已在运行")
            return
        
        self.is_running = True
        
        # 为所有启用的任务添加调度
        for task in self.tasks.values():
            if task.enabled:
                self._schedule_task(task)
        
        # 启动 APScheduler
        self.scheduler.start()
        
        # 启动消费者线程
        self.consumer_thread = threading.Thread(
            target=self._task_consumer,
            daemon=True,
            name="TaskConsumer"
        )
        self.consumer_thread.start()
        
        self._log(f"✓ 调度器已启动 (任务数: {len(self.tasks)})")
    
    def stop(self):
        """停止调度器和消费者线程"""
        if not self.is_running:
            self._log("⚠ 调度器未运行")
            return
        
        self._log("正在停止调度器...")
        
        # 停止标志
        self.is_running = False
        
        # 停止 APScheduler
        self.scheduler.shutdown(wait=False)
        
        # 等待消费者线程结束
        if self.consumer_thread and self.consumer_thread.is_alive():
            self.consumer_thread.join(timeout=5)
        
        # 保存任务状态
        self.save_tasks()
        
        self._log("✓ 调度器已停止")
    
    def load_tasks(self):
        """从配置文件加载任务"""
        try:
            if not self.config_path.exists():
                self._log("配置文件不存在，使用空任务列表")
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.tasks.clear()
            for task_data in data.get("tasks", []):
                task = SyncTask.from_dict(task_data)
                # 重置状态为 IDLE（避免启动时状态不一致）
                task.update_status(TaskStatus.IDLE)
                self.tasks[task.id] = task
            
            self._log(f"✓ 已加载 {len(self.tasks)} 个任务")
            
        except Exception as e:
            self._log(f"✗ 加载任务配置失败: {str(e)}")
    
    def save_tasks(self):
        """保存任务到配置文件"""
        try:
            data = {
                "tasks": [task.to_dict() for task in self.tasks.values()],
                "last_saved": datetime.now().isoformat()
            }
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            self._log(f"✗ 保存任务配置失败: {str(e)}")
    
    def trigger_task_now(self, task_id: str) -> bool:
        """
        立即触发任务执行（手动触发）
        
        Args:
            task_id: 任务ID
            
        Returns:
            是否成功加入队列
        """
        if task_id not in self.tasks:
            self._log(f"任务不存在: {task_id}")
            return False
        
        task = self.tasks[task_id]
        
        if task.status != TaskStatus.IDLE:
            self._log(f"⚠ 任务状态非空闲，无法立即执行: {task.name} (状态: {task.status.value})")
            return False
        
        # 手动触发
        self._on_task_triggered(task_id)
        self._log(f"⚡ 手动触发任务: {task.name}")
        return True
    
    def get_queue_size(self) -> int:
        """
        获取当前队列中等待执行的任务数
        
        Returns:
            队列大小
        """
        return self.task_queue.qsize()
    
    def __del__(self):
        """析构函数：确保资源清理"""
        if self.is_running:
            self.stop()
