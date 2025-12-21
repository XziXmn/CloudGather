"""
任务调度管理器
使用 APScheduler 进行定时调度，通过队列解耦调度和执行
"""

import json
import queue
import threading
import time
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from core.models import SyncTask, TaskStatus, ScheduleType
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
        self.task_context_callback: Optional[Callable[[Optional[str]], None]] = None  # 任务上下文回调
        self.task_progress: Dict[str, dict] = {}  # 任务进度缓存: task_id -> progress_info
        self.task_stats: Dict[str, dict] = {}  # 任务最终统计信息: task_id -> stats
        self.delete_queue: List[dict] = []  # 待删除源文件队列
        self._delete_queue_lock = threading.Lock()
        
        # 确保配置目录存在
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_callback:
                self.log_callback(f"✓ 配置目录已创建: {self.config_path.parent}")
        except Exception as e:
            print(f"⚠️ 创建配置目录失败: {e}")
        
        # 确保配置文件存在，避免宿主机挂载目录未生成文件
        self._ensure_config_file()
        
        # 加载已保存的任务
        self.load_tasks()
    
    def set_log_callback(self, callback: Callable[[str], None]):
        """
        设置日志回调函数
        
        Args:
            callback: 日志回调函数
        """
        self.log_callback = callback
    
    def set_task_context_callback(self, callback: Callable[[Optional[str]], None]):
        """
        设置任务上下文回调函数
        
        Args:
            callback: 任务上下文回调函数，参数为当前任务ID或None
        """
        self.task_context_callback = callback
    
    def _log(self, message: str):
        """
        输出日志
        
        Args:
            message: 日志消息
        """
        if self.log_callback:
            self.log_callback(message)
    
    def _schedule_file_deletion(self, task: SyncTask, source_file: Path):
        """根据任务配置为单个文件计算删除时间并加入队列"""
        # 未开启删除则直接返回
        if not getattr(task, "delete_source", False):
            return

        # 允许 0 天表示同步完成后立即删除，负数一律按 0 处理
        delay_days = getattr(task, "delete_delay_days", None)
        if delay_days is None:
            delay_days = 0
        try:
            delay_days = int(delay_days)
        except (TypeError, ValueError):
            delay_days = 0
        if delay_days < 0:
            delay_days = 0

        base_type = (getattr(task, "delete_time_base", "SYNC_COMPLETE") or "SYNC_COMPLETE").upper()

        # 计算基准时间
        try:
            if base_type == "FILE_CREATE":
                stat = source_file.stat()
                base_time = datetime.fromtimestamp(stat.st_ctime)
            else:
                # 默认使用同步完成时间（近似为当前时间）
                base_time = datetime.now()
        except Exception as e:
            self._log(f"⚠ 计算删除时间失败: {source_file} - {e}")
            return

        delete_at = base_time + timedelta(days=delay_days)

        record = {
            "task_id": task.id,
            "source_path": str(source_file),
            "delete_at": delete_at.isoformat(),
            "delete_parent": bool(getattr(task, "delete_parent", False)),
            "time_base": base_type,
        }

        # 写入/更新队列
        with self._delete_queue_lock:
            updated = False
            for item in self.delete_queue:
                if item.get("task_id") == task.id and item.get("source_path") == record["source_path"]:
                    item.update(record)
                    updated = True
                    break
            if not updated:
                self.delete_queue.append(record)

    def _on_file_synced(self, task: SyncTask, source_file: Path, result: str):
        """单个文件同步完成回调，用于调度删除"""
        if result == "Success":
            self._schedule_file_deletion(task, source_file)

    def _process_delete_queue_for_task(self, task: SyncTask):
        """扫描删除队列中属于指定任务且到期的记录，并执行删除"""
        now = datetime.now()
        task_id = task.id
        task_source_root = Path(task.source_path)

        with self._delete_queue_lock:
            queue_copy = list(self.delete_queue)

        remaining = []
        for item in queue_copy:
            # 只处理当前任务的记录，其它任务的记录原样保留
            if item.get("task_id") != task_id:
                remaining.append(item)
                continue

            delete_at_str = item.get("delete_at")
            source_path = item.get("source_path")
            delete_parent = bool(item.get("delete_parent", False))

            if not delete_at_str or not source_path:
                continue

            try:
                delete_at = datetime.fromisoformat(delete_at_str)
            except Exception:
                # 删除时间不可解析时丢弃记录
                continue

            if delete_at > now:
                # 未到删除时间，保留记录
                remaining.append(item)
                continue

            path = Path(source_path)
            try:
                if path.exists():
                    try:
                        path.unlink()
                        self._log(f"🗑 已删除源文件: {path}")
                    except IsADirectoryError:
                        # 极端情况：记录的是目录
                        if path.is_dir():
                            shutil.rmtree(path, ignore_errors=False)
                            self._log(f"🗑 已删除目录: {path}")
                else:
                    self._log(f"ℹ 源文件已不存在，跳过: {path}")
            except Exception as e:
                self._log(f"⚠ 删除源文件失败: {path} - {e}")
                # 删除失败，保留记录以便下次重试
                remaining.append(item)
                continue

            # 处理上级目录（带相似度和安全检查）
            if delete_parent:
                try:
                    parent = path.parent
                    if not parent.exists():
                        continue

                    # 解析关键路径
                    try:
                        parent_resolved = parent.resolve()
                    except Exception:
                        parent_resolved = parent

                    home_dir = Path.home()
                    try:
                        home_resolved = home_dir.resolve()
                    except Exception:
                        home_resolved = home_dir

                    # 系统根目录 / 用户主目录 永远禁止删除
                    root_of_drive = Path(parent_resolved.anchor) if parent_resolved.anchor else None
                    if (root_of_drive is not None and parent_resolved == root_of_drive) or parent_resolved == home_resolved:
                        self._log(f"⚠ 为安全起见，未删除关键目录: {parent_resolved}")
                        continue

                    # 限制在任务源目录内，且不能删除任务源目录本身
                    try:
                        root = task_source_root
                        root_resolved = root.resolve()
                    except Exception:
                        root_resolved = root

                    # parent 必须是 root 的子目录（严格），否则不删除
                    if root_resolved not in parent_resolved.parents:
                        self._log(f"⚠ 为安全起见，未删除上级目录（不在任务源目录内或为源目录本身）: {parent}")
                        continue

                    # 相似度匹配：目录名与文件名（去扩展名）需具有足够共同前缀
                    file_name = path.stem.lower()
                    dir_name = parent_resolved.name.lower()
                    if not file_name or not dir_name:
                        self._log(f"⚠ 目录/文件名为空，跳过上级目录删除: {parent}")
                        continue

                    prefix_len = 0
                    for ch1, ch2 in zip(file_name, dir_name):
                        if ch1 != ch2:
                            break
                        prefix_len += 1

                    min_len = min(len(file_name), len(dir_name))
                    similarity = getattr(task, "delete_parent_similarity", 60)
                    try:
                        similarity = int(similarity)
                    except (TypeError, ValueError):
                        similarity = 60
                    if similarity < 0:
                        similarity = 0
                    if similarity > 100:
                        similarity = 100
                    required_prefix = int(min_len * (similarity / 100.0)) if min_len > 0 else 0
                    # 共同前缀长度需超过较短名称长度的指定比例
                    if min_len == 0 or prefix_len < required_prefix:
                        self._log(
                            f"⚠ 上级目录与文件名相似度不足，跳过删除: dir={dir_name}, file={file_name}, "
                            f"common_prefix={prefix_len}/{min_len}, required={required_prefix}"
                        )
                        continue

                    # 通过安全和相似度检查后，递归删除上级目录
                    shutil.rmtree(parent, ignore_errors=False)
                    self._log(f"🗑 已强制删除上级目录: {parent}")
                except Exception as e:
                    self._log(f"⚠ 删除上级目录失败: {path.parent} - {e}")

        with self._delete_queue_lock:
            self.delete_queue = remaining

    def _update_progress(self, task_id: str, stats: dict):
        """
        更新任务进度
        
        Args:
            task_id: 任务ID
            stats: 同步统计信息
        """
        done = stats["success"] + stats["skipped_ignored"] + stats["skipped_active"] + stats["skipped_unchanged"] + stats.get("skipped_filtered", 0) + stats["failed"]
        total = stats["total"]
        percent = (done / total * 100) if total > 0 else 0
        
        self.task_progress[task_id] = {
            "done": done,
            "total": total,
            "success": stats["success"],
            "skipped": stats["skipped_ignored"] + stats["skipped_active"] + stats["skipped_unchanged"] + stats.get("skipped_filtered", 0),
            "failed": stats["failed"],
            "percent": round(percent, 1)
        }
    
    def _ensure_config_file(self):
        """确保配置文件存在，若缺失则创建空文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.config_path.exists():
                data = {
                    "tasks": [],
                    "last_saved": datetime.now().isoformat()
                }
                self.config_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
        except Exception as e:
            # 使用 print 保证启动阶段也能看到
            print(f"⚠️ 无法创建配置文件 {self.config_path}: {e}")
            if self.log_callback:
                self.log_callback(f"⚠️ 无法创建配置文件: {self.config_path} - {e}")
    
    def _validate_task_paths(self, task: SyncTask) -> bool:
        """检查任务的源/目标目录可用性，并在需要时创建目标目录"""
        try:
            source = Path(task.source_path)
            target = Path(task.target_path)
            
            if not source.exists():
                self._log(f"✗ 源目录不存在: {source}")
                return False
            if not source.is_dir():
                self._log(f"✗ 源路径不是目录: {source}")
                return False
            if not os.access(source, os.R_OK):
                self._log(f"✗ 没有读取源目录的权限: {source}")
                return False
            
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                self._log(f"📁 已创建目标目录: {target}")
            if not target.is_dir():
                self._log(f"✗ 目标路径不是目录: {target}")
                return False
            if not os.access(target, os.W_OK):
                self._log(f"✗ 没有写入目标目录的权限: {target}")
                return False
            
            return True
        except PermissionError as e:
            self._log(f"✗ 目录权限不足: {e}")
            return False
        except Exception as e:
            self._log(f"✗ 目录检查失败: {e}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
            return False
    
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
            
            self._log(f"✓ 任务添加完成: {task.name}")
            return True
            
        except Exception as e:
            self._log(f"✗ 添加任务失败: {task.name} - {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
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
        # 根据调度类型选择不同的 trigger
        if task.schedule_type == ScheduleType.CRON:
            # Cron 表达式调度
            if not task.cron_expression:
                self._log(f"⚠ 任务 {task.name} 的 Cron 表达式为空，跳过调度")
                return
            try:
                # 解析 cron 表达式：分 时 日 月 星期
                parts = task.cron_expression.strip().split()
                if len(parts) == 5:
                    minute, hour, day, month, day_of_week = parts
                    trigger = CronTrigger(
                        minute=minute,
                        hour=hour,
                        day=day,
                        month=month,
                        day_of_week=day_of_week
                    )
                    self._log(f"任务已调度 (Cron): {task.name} ({task.cron_expression})")
                else:
                    self._log(f"⚠ 任务 {task.name} 的 Cron 表达式格式错误: {task.cron_expression}")
                    return
            except Exception as e:
                self._log(f"⚠ 解析 Cron 表达式失败: {task.name} - {str(e)}")
                return
        else:
            # 间隔调度（默认）
            trigger = IntervalTrigger(seconds=task.interval)
            self._log(f"任务已调度 (Interval): {task.name} (间隔: {task.interval}s)")
        
        self.scheduler.add_job(
            func=self._on_task_triggered,
            trigger=trigger,
            id=task.id,
            args=[task.id],
            replace_existing=True
        )
    
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
        后台任务线程：从队列取出任务并执行同步
        """
        self._log("📌 任务线程已启动")
        
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
                
                # 在执行同步前处理该任务已到期的删除队列
                try:
                    self._process_delete_queue_for_task(task)
                except Exception as e:
                    self._log(f"⚠ 处理删除队列失败: {task.name} - {e}")
                
                # 设置当前任务上下文
                if self.task_context_callback:
                    self.task_context_callback(task_id)
                
                # 更新状态为 RUNNING
                task.update_status(TaskStatus.RUNNING)
                self._log(f"▶ 开始执行任务: {task.name}")
                
                # 运行前校验路径，并在目标缺失时尝试创建
                if not self._validate_task_paths(task):
                    task.update_status(TaskStatus.ERROR)
                    self._log(f"✗ 路径检查失败，任务终止: {task.name}")
                    if self.task_context_callback:
                        self.task_context_callback(None)
                    self.task_queue.task_done()
                    self.save_tasks()
                    continue
                
                # 执行同步
                try:
                    syncer = FileSyncer(
                        source_dir=task.source_path,
                        target_dir=task.target_path
                    )
                    
                    stats = syncer.sync_directory(
                        overwrite_existing=task.overwrite_existing,
                        rule_not_exists=task.rule_not_exists,
                        rule_size_diff=task.rule_size_diff,
                        rule_mtime_newer=task.rule_mtime_newer,
                        thread_count=task.thread_count,
                        log_callback=self._log,
                        progress_callback=lambda s: self._update_progress(task_id, s),
                        is_slow_storage=task.is_slow_storage,
                        size_min_bytes=task.size_min_bytes,
                        size_max_bytes=task.size_max_bytes,
                        suffix_mode=task.suffix_mode,
                        suffix_list=task.suffix_list,
                        file_result_callback=lambda src, dst, result: self._on_file_synced(task, src, result)
                    )
                    
                    # 同步完成后再次处理该任务删除队列（确保延迟为 0 的记录立即执行）
                    try:
                        self._process_delete_queue_for_task(task)
                    except Exception as e:
                        self._log(f"⚠ 同步完成后处理删除队列失败: {task.name} - {e}")
                    
                    # 更新状态为 IDLE
                    task.update_status(TaskStatus.IDLE)
                    task.update_last_run_time()
                    
                    # 保存最终统计信息
                    total_skipped = stats['skipped_ignored'] + stats['skipped_active'] + stats['skipped_unchanged'] + stats.get('skipped_filtered', 0)
                    self.task_stats[task_id] = {
                        "total": stats['total'],
                        "success": stats['success'],
                        "skipped": total_skipped,
                        "failed": stats['failed'],
                        "skipped_filtered": stats.get('skipped_filtered', 0)
                    }
                    
                    self._log(
                        f"✓ 任务执行完成: {task.name} "
                        f"(总文件数: {stats['total']} "
                        f"成功: {stats['success']} "
                        f"跳过: {total_skipped} "
                        f"失败: {stats['failed']})"
                    )
                    
                except Exception as e:
                    # 更新状态为 ERROR
                    task.update_status(TaskStatus.ERROR)
                    self._log(f"✗ 任务执行失败: {task.name} - {str(e)}")
                    import traceback
                    self._log(f"错误详情: {traceback.format_exc()}")
                
                finally:
                    # 清除任务进度缓存
                    self.task_progress.pop(task_id, None)
                    
                    # 清除任务上下文
                    if self.task_context_callback:
                        self.task_context_callback(None)
                    
                    # 标记任务完成
                    self.task_queue.task_done()
                    
                    # 保存任务状态
                    self.save_tasks()
                
            except Exception as e:
                self._log(f"任务线程异常: {str(e)}")
                import traceback
                self._log(f"错误详情: {traceback.format_exc()}")
                time.sleep(1)
        
        self._log("📌 任务线程已停止")
    
    def start(self):
        """启动调度器和任务线程"""
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
        
        # 启动任务线程
        self.consumer_thread = threading.Thread(
            target=self._task_consumer,
            daemon=True,
            name="TaskConsumer"
        )
        self.consumer_thread.start()
        
        self._log(f"✓ 调度器已启动 (任务数: {len(self.tasks)})")
    
    def stop(self):
        """停止调度器和任务线程"""
        if not self.is_running:
            self._log("⚠ 调度器未运行")
            return
        
        self._log("正在停止调度器...")
        
        # 停止标志
        self.is_running = False
        
        # 停止 APScheduler
        self.scheduler.shutdown(wait=False)
        
        # 等待任务线程结束
        if self.consumer_thread and self.consumer_thread.is_alive():
            self.consumer_thread.join(timeout=5)
        
        # 保存任务状态
        self.save_tasks()
        
        self._log("✓ 调度器已停止")
    
    def load_tasks(self):
        """从配置文件加载任务"""
        try:
            if not self.config_path.exists():
                self._log(f"ℹ️ 配置文件不存在，使用空任务列表")
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 加载待删除文件队列
            with self._delete_queue_lock:
                self.delete_queue = data.get("delete_queue", [])
            
            self.tasks.clear()
            loaded_count = 0
            failed_count = 0
            
            for task_data in data.get("tasks", []):
                try:
                    task = SyncTask.from_dict(task_data)
                    # 重置状态为 IDLE（避免启动时状态不一致）
                    task.update_status(TaskStatus.IDLE)
                    self.tasks[task.id] = task
                    loaded_count += 1
                    
                except Exception as e:
                    task_name = task_data.get('name', '未知任务')
                    self._log(f"✗ 加载任务失败: {task_name} - {str(e)}")
                    failed_count += 1
            
            # 提示加载结果
            if failed_count > 0:
                self._log(f"⚠️ 有 {failed_count} 个任务加载失败")
            
            self._log(f"✓ 已加载 {loaded_count} 个任务")
            
        except Exception as e:
            self._log(f"✗ 加载任务配置失败: {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
    
    def save_tasks(self):
        """保存任务到配置文件"""
        try:
            # 确保配置目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with self._delete_queue_lock:
                delete_queue = list(self.delete_queue)
            
            data = {
                "tasks": [task.to_dict() for task in self.tasks.values()],
                "last_saved": datetime.now().isoformat(),
                "delete_queue": delete_queue
            }
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self._log(f"💾 配置已保存")
            
        except Exception as e:
            self._log(f"✗ 保存任务配置失败: {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
    
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
    
    def get_next_run_time(self, task_id: str):
        """
        获取任务的下次执行时间
        
        Args:
            task_id: 任务ID
            
        Returns:
            datetime 对象，如果任务未启用或不存在则返回 None
        """
        if task_id not in self.tasks:
            return None
        
        task = self.tasks[task_id]
        
        # 如果任务未启用，返回 None
        if not task.enabled:
            return None
        
        # 从 APScheduler 获取下次执行时间
        job = self.scheduler.get_job(task_id)
        if job and job.next_run_time:
            return job.next_run_time
        
        return None
    
    def __del__(self):
        """析构函数：确保资源清理"""
        if self.is_running:
            self.stop()
