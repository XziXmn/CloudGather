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
from typing import Dict, List, Optional, Callable, Set
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from core.models import SyncTask, TaskStatus, ScheduleType, StrmTask
from core.worker import FileSyncer, WebDavSyncer
from core.database import Database

# 配置文件 Schema 版本号，用于兼容旧版配置并做迁移
CONFIG_SCHEMA_VERSION = 1


class TaskScheduler:
    """任务调度管理器（支持多任务系统）"""
    
    def __init__(self, config_path: str = "config/tasks.json", strm_config_path: str = "config/strm_tasks.json"):
        """
        初始化调度器
        
        Args:
            config_path: 同步任务配置文件路径
            strm_config_path: STRM 任务配置文件路径
        """
        self.config_path = Path(config_path)
        self.strm_config_path = Path(strm_config_path)
        
        # 任务存储：使用不同的字典分开存储
        self.tasks: Dict[str, SyncTask] = {}  # task_id -> SyncTask
        self.strm_tasks: Dict[str, StrmTask] = {}  # task_id -> StrmTask
        
        self.task_queue = queue.Queue()  # 任务执行队列（元组：(system_key, task_id)）
        self.scheduler = BackgroundScheduler()  # APScheduler 后台调度器
        self.consumer_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.log_callback: Optional[Callable[[str], None]] = None
        self.task_context_callback: Optional[Callable[[Optional[str]], None]] = None  # 任务上下文回调
        self.task_progress: Dict[str, dict] = {}  # 任务进度缓存: task_id -> progress_info
        self.task_stats: Dict[str, dict] = {}  # 任务最终统计信息: task_id -> stats
        
        # 初始化数据库（SQLite）
        db_path = self.config_path.parent / "cloudgather.db"
        self.db = Database(str(db_path))
        
        # 向后兼容：保留内存队列（已废弃，仅用于迁移）
        self.delete_queue: List[dict] = []
        self._delete_queue_lock = threading.Lock()
        
        # 确保配置目录存在
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.strm_config_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_callback:
                self.log_callback(f"✓ 配置目录已创建: {self.config_path.parent}")
        except Exception as e:
            print(f"⚠️ 创建配置目录失败: {e}")
        
        # 确保配置文件存在，避免宿主机挂载目录未生成文件
        self._ensure_config_file()
        self._ensure_strm_config_file()
        
        # 自动检测并执行缓存迁移
        self._auto_migrate_cache_if_needed()
        
        # 加载已保存的任务
        self.load_tasks()
        self.load_strm_tasks()
    
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

        # 写入数据库（替代内存队列）
        try:
            self.db.add_delete_record(
                task_id=task.id,
                source_path=str(source_file),
                delete_at=delete_at.isoformat(),
                delete_parent=bool(getattr(task, "delete_parent", False)),
                time_base=base_type
            )
        except Exception as e:
            self._log(f"⚠ 添加删除记录失败: {source_file} - {e}")

    def _on_file_synced(self, task: SyncTask, source_file: Path, result: str):
        """单个文件同步完成回调，用于调度删除和更新缓存"""
        # 更新缓存状态
        status_map = {
            "Success": "SYNCED",
            "Skipped (Unchanged)": "SKIPPED",
            "Skipped (Filtered)": "SKIPPED",
            "Skipped (Ignored)": "SKIPPED",
            "Skipped (Active)": "PENDING",
            "Failed": "FAILED"
        }
        
        sync_status = status_map.get(result, "PENDING")
        error_msg = None if sync_status != "FAILED" else result
        
        try:
            stat = source_file.stat()
            self.db.upsert_file_cache(
                task_id=task.id,
                path=str(source_file),
                size=stat.st_size,
                mtime=stat.st_mtime,
                sync_status=sync_status,
                synced_at=datetime.now().isoformat() if sync_status in ("SYNCED", "SKIPPED") else None,
                last_error=error_msg
            )
            
            # 添加历史记录（带去重）
            self.db.add_history_record(
                task_id=task.id,
                path=str(source_file),
                status=sync_status,
                details=result if sync_status == "FAILED" else None
            )
        except Exception as e:
            self._log(f"⚠ 更新文件缓存失败: {source_file} - {e}")

        # 调度删除
        if result in ("Success", "Skipped (Unchanged)"):
            self._schedule_file_deletion(task, source_file)

    def _process_delete_queue_for_task(self, task: SyncTask):
        """扫描删除队列中属于指定任务且到期的记录，并执行删除"""
        now = datetime.now()
        task_id = task.id
        task_source_root = Path(task.source_path)

        # 从数据库获取到期记录
        try:
            expired_records = self.db.get_expired_records(task_id, now.isoformat())
        except Exception as e:
            self._log(f"⚠ 获取删除队列失败: {e}")
            return

        # 删除统计
        delete_stats = {
            "files_deleted": 0,
            "dirs_deleted": 0,
            "files_not_exist": 0,
            "files_failed": 0
        }
        # 本轮成功删除的源文件路径列表（用于后续目录清理）
        deleted_files: List[Path] = []
        deleted_record_ids: List[int] = []  # 已处理的记录ID
        
        for record in expired_records:
            record_id = record.get("id")
            source_path = record.get("source_path")
            delete_parent = bool(record.get("delete_parent", False))

            if not source_path:
                continue

            path = Path(source_path)
            try:
                # 安全性增强：验证同步记录
                if not self.db.is_file_synced(task_id, source_path):
                    self._log(f"🛡 安全拦截：文件未确认同步，拒绝删除: {path}")
                    # 不移除记录，标记为失败以便后续重试或人工检查
                    delete_stats["files_failed"] += 1
                    continue

                if path.exists():
                    try:
                        path.unlink()
                        delete_stats["files_deleted"] += 1
                        deleted_files.append(path)
                        deleted_record_ids.append(record_id)
                        
                        # 更新缓存树中的删除时间
                        self.db.update_sync_status(
                            task_id=task_id,
                            path=source_path,
                            status="DELETED",
                            deleted_at=datetime.now().isoformat()
                        )
                        
                        # 添加历史记录（带去重）
                        self.db.add_history_record(
                            task_id=task_id,
                            path=source_path,
                            status="DELETED"
                        )
                        
                        self._log(f"🗑 已删除源文件: {path}")
                    except IsADirectoryError:
                        # 极端情况：记录的是目录
                        if path.is_dir():
                            shutil.rmtree(path, ignore_errors=False)
                            delete_stats["dirs_deleted"] += 1
                            deleted_files.append(path)
                            deleted_record_ids.append(record_id)
                            self._log(f"🗑 已删除目录: {path}")
                else:
                    delete_stats["files_not_exist"] += 1
                    deleted_record_ids.append(record_id)  # 文件不存在也从队列中移除
                    self._log(f"ℹ 源文件已不存在，跳过: {path}")
            except Exception as e:
                delete_stats["files_failed"] += 1
                self._log(f"⚠ 删除源文件失败: {path} - {e}")
                # 删除失败不移除记录，下次重试
                continue

        # 从数据库中移除已处理的记录
        try:
            self.db.remove_delete_records_by_id(deleted_record_ids)
        except Exception as e:
            self._log(f"⚠ 清理删除记录失败: {e}")
        
        # 基于本轮成功删除的文件，按任务配置清理上级目录
        try:
            self._cleanup_parent_dirs_for_deleted(task, deleted_files, delete_stats, now)
        except Exception as e:
            self._log(f"⚠ 处理上级目录删除时发生异常: {e}")
        
        # 输出删除统计汇总
        total_deleted = delete_stats["files_deleted"] + delete_stats["dirs_deleted"]
        if total_deleted > 0 or delete_stats["files_not_exist"] > 0 or delete_stats["files_failed"] > 0:
            self._log(
                f"✅ 删除队列处理完成: "
                f"删除文件 {delete_stats['files_deleted']} 个, "
                f"删除目录 {delete_stats['dirs_deleted']} 个, "
                f"已不存在 {delete_stats['files_not_exist']} 个, "
                f"删除失败 {delete_stats['files_failed']} 个"
            )

    def _cleanup_parent_dirs_for_deleted(self, task: SyncTask, deleted_files: List[Path], delete_stats: dict, now: datetime):
        """根据任务配置，为本轮已删除的文件向上尝试删除上级目录"""
        # 未启用目录删除，直接返回
        if not getattr(task, "delete_parent", False):
            return
        if not deleted_files:
            return

        # 解析任务源目录与关键路径
        try:
            root = Path(task.source_path)
            try:
                root_resolved = root.resolve()
            except Exception:
                root_resolved = root
        except Exception:
            return

        home_dir = Path.home()
        try:
            home_resolved = home_dir.resolve()
        except Exception:
            home_resolved = home_dir

        max_levels = 0
        try:
            max_levels = int(getattr(task, "delete_parent_levels", 0) or 0)
        except (TypeError, ValueError):
            max_levels = 0
        if max_levels <= 0:
            return

        # 是否强制删除非空目录（仍然会保护未到期文件）
        force_delete_nonempty = bool(getattr(task, "delete_parent_force", False))

        processed_dirs: Set[Path] = set()

        for file_path in deleted_files:
            # 只处理源目录子树内的文件
            try:
                fp = Path(file_path)
            except Exception:
                continue

            parent = fp.parent
            level = 1

            while level <= max_levels:
                cand = parent
                if cand in processed_dirs:
                    # 已处理过的目录不必重复
                    break

                if not cand.exists():
                    break

                try:
                    cand_resolved = cand.resolve()
                except Exception:
                    cand_resolved = cand

                # 根目录 / 用户主目录 / 任务源目录本身 禁止删除
                root_of_drive = Path(cand_resolved.anchor) if cand_resolved.anchor else None
                if (root_of_drive is not None and cand_resolved == root_of_drive) or cand_resolved == home_resolved:
                    break
                if cand_resolved == root_resolved:
                    # 不删除 source_path 本身，停止向上检查
                    break

                # cand 必须在任务源目录子树内
                if root_resolved not in cand_resolved.parents:
                    break

                # 若目录下还有未到删除时间的文件，则暂缓删除
                if self._has_pending_delete_entries(task_id=task.id, base_dir=cand_resolved, queue_snapshot=[], now=now):
                    break

                # 非强制模式下，仅在目录物理为空时删除
                if not force_delete_nonempty:
                    try:
                        if any(cand.iterdir()):
                            break
                    except Exception:
                        break

                # 安全删除该目录
                try:
                    shutil.rmtree(cand, ignore_errors=False)
                    delete_stats["dirs_deleted"] += 1
                    self._log(f"🗑 已删除上级目录: {cand}")
                except Exception as e:
                    self._log(f"⚠ 删除上级目录失败: {cand} - {e}")
                    break

                processed_dirs.add(cand)
                # 继续向上尝试
                parent = cand.parent
                level += 1

    def _has_pending_delete_entries(self, task_id: str, base_dir: Path, queue_snapshot: List[dict], now: datetime) -> bool:
        """判断指定目录子树下是否存在未到删除时间的记录"""
        # 使用数据库查询
        try:
            pending_records = self.db.get_pending_records(
                task_id=task_id,
                current_time=now.isoformat(),
                base_dir=str(base_dir)
            )
            return len(pending_records) > 0
        except Exception as e:
            self._log(f"⚠ 查询未到期记录失败: {e}")
            # 出错时保守处理，返回 True 避免误删
            return True

    def _update_progress(self, task_id: str, stats: dict):
        """
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
    
    def _auto_migrate_cache_if_needed(self):
        """自动检测并执行缓存迁移（Result-driven Reconstruction）
        在系统启动时检测缓存表是否为空，如果为空则自动执行迁移
        """
        try:
            # 检查缓存表是否为空
            cache_count = self.db.get_cache_count()
            task_count = len(self.tasks) + len(self.strm_tasks)
            
            self._log(f"🔍 缓存自动迁移检查: 缓存记录={cache_count}, 任务总数={task_count}")
            
            # 如果缓存为空但存在任务，则自动执行迁移
            if cache_count == 0 and task_count > 0:
                self._log("🔄 检测到缓存为空，自动启动缓存迁移...")
                
                # 为每个同步任务执行重构
                for task in self.tasks.values():
                    try:
                        self._log(f"🛠 自动重构同步任务缓存: {task.name}")
                        syncer = FileSyncer(
                            source_dir=task.source_path,
                            target_dir=task.target_path,
                            task_id=task.id,
                            db=self.db
                        )
                        stats = syncer.reconstruct_cache_from_target(log_callback=self._log)
                        self._log(f"✅ 同步任务 '{task.name}' 缓存重构完成: 扫描{stats['found']}, 匹配{stats['matched']}, 更新{stats['updated']}")
                    except Exception as e:
                        self._log(f"❌ 同步任务 '{task.name}' 缓存重构失败: {e}")
                
                # 为每个STRM任务执行重构
                for task in self.strm_tasks.values():
                    try:
                        self._log(f"🛠 自动重构STRM任务缓存: {task.name}")
                        from core.strm_generator import StrmGenerator
                        generator = StrmGenerator(task, self._log, self.db)
                        stats = generator.reconstruct_cache_from_target(log_callback=self._log)
                        self._log(f"✅ STRM任务 '{task.name}' 缓存重构完成: 扫描{stats['found']}, 匹配{stats['matched']}, 更新{stats['updated']}")
                    except Exception as e:
                        self._log(f"❌ STRM任务 '{task.name}' 缓存重构失败: {e}")
                
                # 再次检查缓存数量
                final_count = self.db.get_cache_count()
                self._log(f"✅ 缓存自动迁移完成! 新增缓存记录: {final_count}")
            elif cache_count > 0:
                self._log(f"✅ 缓存已存在 ({cache_count} 条记录)，跳过自动迁移")
            else:
                self._log("ℹ️ 无任务配置，无需执行缓存迁移")
                
        except Exception as e:
            self._log(f"⚠ 缓存自动迁移检查失败: {e}")

    def _ensure_config_file(self):
        """确保配置文件存在，若缺失则创建空文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.config_path.exists():
                data = {
                    "schema_version": CONFIG_SCHEMA_VERSION,
                    "tasks": [],
                    "last_saved": datetime.now().isoformat(),
                    "delete_queue": []
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
    
    def _ensure_strm_config_file(self):
        """确保 STRM 任务配置文件存在，若缺失则创建空文件"""
        try:
            self.strm_config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.strm_config_path.exists():
                data = {
                    "schema_version": CONFIG_SCHEMA_VERSION,
                    "tasks": [],
                    "last_saved": datetime.now().isoformat()
                }
                self.strm_config_path.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding='utf-8'
                )
        except Exception as e:
            print(f"⚠️ 无法创建 STRM 配置文件 {self.strm_config_path}: {e}")
            if self.log_callback:
                self.log_callback(f"⚠️ 无法创建 STRM 配置文件: {self.strm_config_path} - {e}")
    
    def _validate_task_paths(self, task: SyncTask) -> bool:
        """检查任务的源/目标目录可用性，并在需要时创建目标目录"""
        try:
            if getattr(task, "copy_mode", "COPY") == "SYMLINK" and getattr(task, "delete_source", False):
                self._log("✗ 软链接模式不能同时删除源文件，否则目标链接会失效")
                return False
            if getattr(task, "target_type", "LOCAL") == "WEBDAV" and getattr(task, "copy_mode", "COPY") != "COPY":
                self._log("✗ WebDAV 目标只支持复制文件")
                return False

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

            if getattr(task, "target_type", "LOCAL") == "WEBDAV":
                from api.settings import create_webdav_client, load_webdav_config
                config = load_webdav_config()
                if not config.get("url"):
                    self._log("✗ 未配置 WebDAV 服务器")
                    return False
                client = create_webdav_client(config)
                client.ensure_dir(task.target_path)
                return True
            
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
    
    def _schedule_task(self, task, system_key='sync'):
        """
        将任务添加到 APScheduler（支持多任务系统）
        
        Args:
            task: 任务对象（SyncTask 或 StrmTask）
            system_key: 系统标识（'sync' 或 'strm'）
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
        
        # 关键改造：使用 system_key 前缀
        job_id = f"{system_key}_{task.id}"
        
        self.scheduler.add_job(
            func=self._on_task_triggered,
            trigger=trigger,
            id=job_id,  # 使用前缀后的 job_id
            args=[task.id, system_key],  # 传递 system_key
            replace_existing=True
        )
    
    def _on_task_triggered(self, task_id: str, system_key: str = 'sync'):
        """
        定时器触发回调：将任务加入队列（支持多任务系统）
        
        Args:
            task_id: 任务ID
            system_key: 系统标识（'sync' 或 'strm'）
        """
        # 根据 system_key 路由到不同的任务字典
        if system_key == 'sync':
            if task_id not in self.tasks:
                return
            task = self.tasks[task_id]
        elif system_key == 'strm':
            if task_id not in self.strm_tasks:
                return
            task = self.strm_tasks[task_id]
        else:
            self._log(f"⚠ 未知的任务系统: {system_key}")
            return
        
        # 检查任务状态，避免重复入队
        if task.status == TaskStatus.IDLE:
            # 更新状态为 QUEUED
            task.update_status(TaskStatus.QUEUED)
            
            # 将任务信息放入队列（元组：(system_key, task_id)）
            self.task_queue.put((system_key, task_id))
            
            self._log(f"⏱ 任务已加入队列: {task.name} [{system_key}]")
        else:
            self._log(f"⚠ 任务仍在执行中，跳过本次调度: {task.name} (状态: {task.status.value})")
    
    def _task_consumer(self):
        """
        后台任务线程：从队列取出任务并执行（支持多任务系统）
        """
        self._log("📌 任务线程已启动")
        
        while self.is_running:
            try:
                # 从队列取出任务信息（超时1秒，避免阻塞关闭）
                try:
                    queue_item = self.task_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 解析队列项：(system_key, task_id)
                if isinstance(queue_item, tuple) and len(queue_item) == 2:
                    system_key, task_id = queue_item
                else:
                    # 向后兼容：旧版本只有 task_id
                    system_key = 'sync'
                    task_id = queue_item
                
                # 根据 system_key 路由到不同的任务系统
                if system_key == 'sync':
                    if task_id not in self.tasks:
                        self._log(f"⚠ 同步任务不存在，跳过: {task_id}")
                        self.task_queue.task_done()
                        continue
                    task = self.tasks[task_id]
                    self._execute_sync_task(task)
                    
                elif system_key == 'strm':
                    if task_id not in self.strm_tasks:
                        self._log(f"⚠ STRM 任务不存在，跳过: {task_id}")
                        self.task_queue.task_done()
                        continue
                    task = self.strm_tasks[task_id]
                    self._execute_strm_task(task)
                    
                else:
                    self._log(f"⚠ 未知的任务系统: {system_key}")
                    self.task_queue.task_done()
                    continue
                
            except Exception as e:
                self._log(f"任务线程异常: {str(e)}")
                import traceback
                self._log(f"错误详情: {traceback.format_exc()}")
        
        self._log("📌 任务线程已停止")
    
    def _execute_sync_task(self, task: SyncTask):
        """执行同步任务（原有逻辑）"""
        task_id = task.id
        
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
            return
        
        # 执行同步
        try:
            # 获取系统重试设置
            from api.settings import create_webdav_client, load_system_config, load_webdav_config
            system_config = load_system_config()
            retry_count = system_config.get('sync_retry_count', 3)

            if getattr(task, "target_type", "LOCAL") == "WEBDAV":
                webdav_config = load_webdav_config()
                syncer = WebDavSyncer(
                    source_dir=task.source_path,
                    target_dir=task.target_path,
                    client=create_webdav_client(webdav_config)
                )
                thread_count = 1
            else:
                syncer = FileSyncer(
                    source_dir=task.source_path,
                    target_dir=task.target_path,
                    task_id=task_id,
                    db=self.db
                )
                thread_count = task.thread_count
            
            stats = syncer.sync_directory(
                overwrite_existing=task.overwrite_existing,
                rule_not_exists=task.rule_not_exists,
                rule_size_diff=task.rule_size_diff,
                rule_mtime_newer=task.rule_mtime_newer,
                thread_count=thread_count,
                log_callback=self._log,
                progress_callback=lambda s: self._update_progress(task_id, s),
                is_slow_storage=task.is_slow_storage,
                size_min_bytes=task.size_min_bytes,
                size_max_bytes=task.size_max_bytes,
                suffix_mode=task.suffix_mode,
                suffix_list=task.suffix_list,
                file_result_callback=lambda src, dst, result: self._on_file_synced(task, src, result),
                retry_count=retry_count,
                copy_mode=getattr(task, "copy_mode", "COPY")
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
    
    def _execute_strm_task(self, task: StrmTask):
        """执行 STRM 任务"""
        task_id = task.id
        
        # 设置当前任务上下文
        if self.task_context_callback:
            self.task_context_callback(task_id)
        
        # 更新状态为 RUNNING
        task.update_status(TaskStatus.RUNNING)
        self._log(f"▶ 开始执行 STRM 任务: {task.name}")
        
        # 执行 STRM 生成
        try:
            from core.strm_generator import StrmGenerator
            
            generator = StrmGenerator(
                task=task,
                log_callback=self._log,
                db=self.db
            )
            
            stats = generator.run(
                progress_callback=lambda s: self._update_progress(task_id, s)
            )
            
            # 更新状态为 IDLE
            task.update_status(TaskStatus.IDLE)
            task.update_last_run_time()
            
            # 保存统计信息
            self.task_stats[task_id] = stats
            
            self._log(
                f"✓ STRM 任务完成: {task.name} "
                f"(总计: {stats['total']} "
                f"成功: {stats['success']} "
                f"跳过: {stats['skipped']} "
                f"失败: {stats['failed']})"
            )
            
        except Exception as e:
            # 更新状态为 ERROR
            task.update_status(TaskStatus.ERROR)
            self._log(f"✗ STRM 任务失败: {task.name} - {str(e)}")
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
            self.save_strm_tasks()
    
    def start(self):
        """启动调度器和任务线程（支持多任务系统）"""
        if self.is_running:
            self._log("⚠ 调度器已在运行")
            return
        
        self.is_running = True
        
        # 为所有启用的同步任务添加调度
        for task in self.tasks.values():
            if task.enabled:
                self._schedule_task(task, system_key='sync')
        
        # 为所有启用的 STRM 任务添加调度
        for task in self.strm_tasks.values():
            if task.enabled:
                self._schedule_task(task, system_key='strm')
        
        # 启动 APScheduler
        self.scheduler.start()
        
        # 启动任务线程
        self.consumer_thread = threading.Thread(
            target=self._task_consumer,
            daemon=True,
            name="TaskConsumer"
        )
        self.consumer_thread.start()
        
        total_tasks = len(self.tasks) + len(self.strm_tasks)
        self._log(f"✓ 调度器已启动 (同步任务: {len(self.tasks)}, STRM 任务: {len(self.strm_tasks)}, 总计: {total_tasks})")
    
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
        self.save_strm_tasks()
        
        self._log("✓ 调度器已停止")
    
    def _migrate_v0_to_v1(self, data: dict) -> dict:
        """将无 schema_version 的旧配置迁移到 v1 结构
        - 确保 tasks 为列表
        - 确保 delete_queue 为列表
        """
        if not isinstance(data.get("tasks"), list):
            data["tasks"] = []
        if not isinstance(data.get("delete_queue"), list):
            data["delete_queue"] = []
        return data

    def _migrate_config(self, data: dict) -> dict:
        """根据 schema_version 对配置数据进行迁移"""
        old_version = data.get("schema_version", 0)
        try:
            version = int(old_version or 0)
        except (TypeError, ValueError):
            version = 0

        # 目前仅有 v0 -> v1 的迁移
        if version < 1:
            data = self._migrate_v0_to_v1(data)
            version = 1
            try:
                self._log(f"ℹ️ 检测到旧版配置，已从 schema_version {old_version} 迁移到 {version}")
            except Exception:
                pass

        # 将版本号提升到当前版本
        data["schema_version"] = CONFIG_SCHEMA_VERSION
        return data

    def load_tasks(self):
        """从配置文件加载同步任务"""
        try:
            if not self.config_path.exists():
                self._log(f"ℹ️ 配置文件不存在，使用空任务列表")
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 根据 schema_version 对配置进行迁移，兼容旧版本
            data = self._migrate_config(data)

            # 迁移删除队列从 JSON 到 SQLite（一次性迁移）
            if self.db.get_config("delete_queue_migrated") != "true":
                json_delete_queue = data.get("delete_queue", [])
                if json_delete_queue:
                    try:
                        migrated_count = self.db.migrate_from_json(json_delete_queue)
                        self._log(f"✓ 已迁移 {migrated_count} 条删除记录到数据库")
                        self.db.set_config("delete_queue_migrated", "true")
                        self.db.set_config("migration_time", datetime.now().isoformat())
                    except Exception as e:
                        self._log(f"⚠ 迁移删除队列失败: {e}")
                else:
                    # 没有旧数据需要迁移，直接标记为已迁移
                    self.db.set_config("delete_queue_migrated", "true")

            # 加载待删除文件队列（已废弃，保留用于向后兼容）
            with self._delete_queue_lock:
                self.delete_queue = []  # 不再从 JSON 加载，改用数据库

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
            
            self._log(f"✓ 已加载 {loaded_count} 个同步任务")
            
        except Exception as e:
            self._log(f"✗ 加载同步任务配置失败: {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
    
    def load_strm_tasks(self):
        """从配置文件加载 STRM 任务"""
        try:
            if not self.strm_config_path.exists():
                self._log(f"ℹ️ STRM 配置文件不存在，使用空任务列表")
                return
            
            with open(self.strm_config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 根据 schema_version 对配置进行迁移
            data = self._migrate_config(data)
            
            self.strm_tasks.clear()
            loaded_count = 0
            failed_count = 0
            
            for task_data in data.get("tasks", []):
                try:
                    task = StrmTask.from_dict(task_data)
                    # 重置状态为 IDLE
                    task.update_status(TaskStatus.IDLE)
                    self.strm_tasks[task.id] = task
                    loaded_count += 1
                    
                except Exception as e:
                    task_name = task_data.get('name', '未知 STRM 任务')
                    self._log(f"✗ 加载 STRM 任务失败: {task_name} - {str(e)}")
                    failed_count += 1
            
            if failed_count > 0:
                self._log(f"⚠️ 有 {failed_count} 个 STRM 任务加载失败")
            
            self._log(f"✓ 已加载 {loaded_count} 个 STRM 任务")
            
        except Exception as e:
            self._log(f"✗ 加载 STRM 任务配置失败: {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
    
    def save_tasks(self):
        """保存同步任务到配置文件（删除队列已迁移到数据库，不再保存到 JSON）"""
        try:
            # 确保配置目录存在
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "schema_version": CONFIG_SCHEMA_VERSION,
                "tasks": [task.to_dict() for task in self.tasks.values()],
                "last_saved": datetime.now().isoformat(),
                # 删除队列已迁移到数据库，JSON 中只保留空数组（向后兼容）
                "delete_queue": []
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # self._log(f"💾 同步任务配置已保存")
            
        except Exception as e:
            self._log(f"✗ 保存同步任务配置失败: {str(e)}")
            import traceback
            self._log(f"错误详情: {traceback.format_exc()}")
    
    def save_strm_tasks(self):
        """保存 STRM 任务到配置文件"""
        try:
            # 确保配置目录存在
            self.strm_config_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "schema_version": CONFIG_SCHEMA_VERSION,
                "tasks": [task.to_dict() for task in self.strm_tasks.values()],
                "last_saved": datetime.now().isoformat()
            }
            
            with open(self.strm_config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            # self._log(f"💾 STRM 任务配置已保存")
            
        except Exception as e:
            self._log(f"✗ 保存 STRM 任务配置失败: {str(e)}")
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
        # 关闭数据库连接
        try:
            self.db.close()
        except Exception:
            pass
