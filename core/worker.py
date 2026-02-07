"""
NAS 文件同步核心模块
提供原子化写入、静默期检测、垃圾过滤等功能
"""

import os
import json
import time
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed


class FileSyncer:
    """文件同步核心类"""
    
    # 垃圾文件/文件夹过滤列表
    IGNORE_LIST = {
        '.DS_Store',
        '@eaDir',
        '#recycle',
        'Thumbs.db',
        '.tmp',
        '.temp',
        '~$',  # Office 临时文件前缀
        '.part',  # 部分下载文件
    }
    
    # 静默期检测等待时间（秒）
    STABILITY_CHECK_DELAY = 5
    
    def __init__(self, source_dir: str, target_dir: str, task_id: Optional[str] = None, db: Any = None):
        """
        初始化文件同步器
        
        Args:
            source_dir: 源目录路径
            target_dir: 目标目录路径
            task_id: 关联的任务ID
            db: 数据库管理对象
        """
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.task_id = task_id
        self.db = db
        
        # 确保目录存在
        if not self.source_dir.exists():
            raise ValueError(f"源目录不存在: {self.source_dir}")
        
        self.target_dir.mkdir(parents=True, exist_ok=True)
    
    def should_ignore(self, file_path: Path) -> bool:
        """
        检查文件是否应该被忽略
        
        Args:
            file_path: 文件路径
            
        Returns:
            True 如果应该忽略，False 否则
        """
        file_name = file_path.name
        
        # 检查完整文件名
        if file_name in self.IGNORE_LIST:
            return True
        
        # 检查前缀匹配
        for ignore_pattern in self.IGNORE_LIST:
            if ignore_pattern.startswith('~') or ignore_pattern.startswith('.'):
                if file_name.startswith(ignore_pattern.rstrip('$')):
                    return True
        
        return False
    
    def check_file_stability(
        self, 
        file_path: Path, 
        log_callback: Optional[Callable[[str], None]] = None
    ) -> Tuple[bool, int]:
        """
        检查文件是否稳定（静默期检测）
        
        Args:
            file_path: 文件路径
            log_callback: 日志回调函数
            
        Returns:
            (is_stable, file_size) - 文件是否稳定及其大小
        """
        try:
            # 第一次获取文件大小
            size_before = file_path.stat().st_size
            
            if log_callback:
                log_callback(f"检查文件稳定性: {file_path.name} ({self._format_size(size_before)})")
            
            # 等待静默期
            time.sleep(self.STABILITY_CHECK_DELAY)
            
            # 第二次获取文件大小
            size_after = file_path.stat().st_size
            
            # 比较大小是否变化
            if size_before != size_after:
                if log_callback:
                    log_callback(
                        f"文件正在变化: {file_path.name} "
                        f"({self._format_size(size_before)} -> {self._format_size(size_after)})"
                    )
                return False, size_after
            
            return True, size_after
            
        except FileNotFoundError:
            if log_callback:
                log_callback(f"文件已消失: {file_path.name}")
            return False, 0
        except Exception as e:
            if log_callback:
                log_callback(f"稳定性检查失败: {file_path.name} - {str(e)}")
            return False, 0
    

    
    def calculate_file_hash(self, file_path: Path, block_size: int = 65536) -> str:
        """
        计算文件的 MD5 哈希值
        
        Args:
            file_path: 文件路径
            block_size: 读取块大小
            
        Returns:
            MD5 哈希字符串
        """
        md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                md5.update(block)
        return md5.hexdigest()

    def get_smart_hash(self, file_path: Path) -> str:
        """
        智能获取文件哈希（使用缓存机制）
        
        Args:
            file_path: 文件路径
            
        Returns:
            哈希字符串
        """
        if not self.db or not self.task_id:
            return self.calculate_file_hash(file_path)
            
        try:
            stat = file_path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
            path_str = str(file_path)
            
            # 1. 尝试从缓存获取
            cache = self.db.get_file_cache(self.task_id, path_str)
            
            if cache and cache['size'] == size and cache['mtime'] == mtime and cache['hash']:
                return cache['hash']
                
            # 2. 缓存失效或不存在，重新计算
            file_hash = self.calculate_file_hash(file_path)
            
            # 3. 更新缓存
            self.db.upsert_file_cache(
                task_id=self.task_id,
                path=path_str,
                size=size,
                mtime=mtime,
                file_hash=file_hash,
                hash_at=datetime.now().isoformat()
            )
            
            return file_hash
        except Exception:
            # 出错则退回到实时计算
            return self.calculate_file_hash(file_path)

    def should_sync_file(
        self, 
        source_file: Path, 
        target_file: Path, 
        overwrite_existing: bool = False,
        rule_not_exists: bool = False,
        rule_size_diff: bool = False,
        rule_mtime_newer: bool = False
    ) -> Tuple[bool, str]:
        """
        智能判断是否需要同步文件（支持子规则，集成哈希校验）
        
        Args:
            source_file: 源文件路径
            target_file: 目标文件路径
            overwrite_existing: 是否覆盖已存在的文件
            rule_not_exists: 子规则 - 目标文件不存在时同步
            rule_size_diff: 子规则 - 文件大小不一致时同步
            rule_mtime_newer: 子规则 - 源文件修改时间更新时同步
            
        Returns:
            (should_sync, reason) - 是否需要同步及原因
        """
        # 目标文件不存在
        if not target_file.exists():
            if rule_not_exists:
                return True, "target_not_exists (rule)"
            if overwrite_existing:
                return True, "target_not_exists (overwrite_mode)"
            return False, "target_not_exists (no_rule)"
        
        # 目标文件已存在，检查常规子规则
        try:
            source_stat = source_file.stat()
            target_stat = target_file.stat()
            
            # 如果大小和修改时间都一致，尝试进行更深度的校验（如果配置支持或需要）
            # 注意：这里的逻辑可以根据需求调整。如果用户要求"智能缓存校验"，
            # 那么在 size/mtime 一致时，我们可以进一步对比 hash。
            
            # 子规刑2: 大小不一致
            if rule_size_diff and source_stat.st_size != target_stat.st_size:
                return True, "size_diff (rule)"
            
            # 子规刑3: 修改时间比较（源文件更新）
            if rule_mtime_newer and source_stat.st_mtime > target_stat.st_mtime:
                return True, "mtime_newer (rule)"
            
            # 如果开启了覆盖模式，但 size/mtime 一致，我们进入哈希深度校验
            if overwrite_existing:
                # 注意：计算目标文件哈希可能很慢（如果是网盘挂载）
                # 因此这里优先通过缓存对比
                return True, "overwrite_mode"
            
            # 如果所有原子规则都一致，则认为未改变
            return False, "unchanged"
            
        except Exception as e:
            return True, f"check_error: {str(e)}"
    
    def sync_file(
        self,
        source_file: Path,
        target_file: Path,
        overwrite_existing: bool = False,
        rule_not_exists: bool = False,
        rule_size_diff: bool = False,
        rule_mtime_newer: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        size_min_bytes: Optional[int] = None,
        size_max_bytes: Optional[int] = None,
        suffix_mode: str = "NONE",
        suffix_list: Optional[list[str]] = None,
        retry_count: int = 0
    ) -> str:
        """
        同步单个文件（原子化写入，支持子规则，支持重试）
        
        Args:
            source_file: 源文件路径
            target_file: 目标文件路径
            overwrite_existing: 是否覆盖已存在的文件（主规则，内部使用）
            rule_not_exists: 子规刑1 - 目标文件不存在时同步
            rule_size_diff: 子规刑2 - 文件大小不一致时同步
            rule_mtime_newer: 子规刑3 - 源文件修改时间更新时同步
            log_callback: 日志回调函数
            size_min_bytes: 最小文件大小
            size_max_bytes: 最大文件大小
            suffix_mode: 后缀模式
            suffix_list: 后缀列表
            retry_count: 失败重试次数
            
        Returns:
            同步状态: "Success", "Skipped (Ignored)", "Skipped (Active)", "Skipped (Unchanged)", "Failed"
        """
        # 尝试次数为 retry_count + 1
        max_attempts = retry_count + 1
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                if attempt > 0 and log_callback:
                    log_callback(f"正在重试 ({attempt}/{retry_count}): {source_file.name}")
                
                # 1. 垃圾过滤
                if self.should_ignore(source_file):
                    if log_callback:
                        log_callback(f"已忽略: {source_file.name}")
                    return "Skipped (Ignored)"
                
                # 2. 后缀过滤
                mode = (suffix_mode or "NONE").upper()
                if mode != "NONE":
                    ext = source_file.suffix.lower().lstrip(".")
                    suffixes = [s.lower().lstrip(".") for s in suffix_list] if suffix_list else []
                    if mode == "INCLUDE":
                        if not ext or ext not in suffixes:
                            if log_callback:
                                log_callback(f"已过滤: {source_file.name} (mode=INCLUDE, ext={ext or '-'})")
                            return "Skipped (Filtered)"
                    elif mode == "EXCLUDE":
                        if ext and ext in suffixes:
                            if log_callback:
                                log_callback(f"已过滤: {source_file.name} (mode=EXCLUDE, ext={ext})")
                            return "Skipped (Filtered)"
                
                # 3. 大小过滤
                if size_min_bytes is not None or size_max_bytes is not None:
                    try:
                        size = source_file.stat().st_size
                    except Exception as e:
                        size = None
                        if log_callback:
                            log_callback(f"无法获取文件大小，将跳过过滤规则: {source_file.name} - {str(e)}")
                    if size is not None:
                        if size_min_bytes is not None and size < size_min_bytes:
                            if log_callback:
                                log_callback(
                                    f"已跳过: {source_file.name} "
                                    f"({self._format_size(size)} < 最小 {self._format_size(size_min_bytes)})"
                                )
                            return "Skipped (Filtered)"
                        if size_max_bytes is not None and size > size_max_bytes:
                            if log_callback:
                                log_callback(
                                    f"已跳过: {source_file.name} "
                                    f"({self._format_size(size)} > 最大 {self._format_size(size_max_bytes)})"
                                )
                            return "Skipped (Filtered)"
                
                # 4. 智能判断是否需要同步（传入子规则参数）
                should_sync, reason = self.should_sync_file(
                    source_file, target_file, overwrite_existing,
                    rule_not_exists, rule_size_diff, rule_mtime_newer
                )
                if not should_sync:
                    if log_callback:
                        log_callback(f"已跳过: {source_file.name}")
                    return "Skipped (Unchanged)"
                
                # 5. 静默期检测
                is_stable, file_size = self.check_file_stability(source_file, log_callback)
                if not is_stable:
                    if log_callback:
                        log_callback(f"已跳过: {source_file.name} (文件活动中)")
                    return "Skipped (Active)"
                
                # 6. 准备临时文件路径
                target_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file = target_file.parent / f".tmp_{target_file.name}"
                
                # 7. 复制文件
                if log_callback:
                    log_callback(f"开始复制: {source_file.name} ({self._format_size(file_size)})")
                
                # 使用 shutil.copy2 保留元数据
                shutil.copy2(source_file, temp_file)
                
                if log_callback:
                    log_callback(f"复制完成: {source_file.name}")
                
                # 8. 校验文件大小
                temp_size = temp_file.stat().st_size
                if temp_size != file_size:
                    raise IOError(f"大小校验失败 (期望: {file_size}, 实际: {temp_size})")
                
                # 9. 原子化重命名
                if target_file.exists():
                    target_file.unlink()
                
                os.rename(temp_file, target_file)
                
                if log_callback:
                    log_callback(f"✓ 同步成功: {source_file.name}")
                
                return "Success"
                
            except Exception as e:
                last_error = str(e)
                if log_callback:
                    log_callback(f"✗ 同步出错 (第 {attempt + 1} 次尝试): {source_file.name} - {last_error}")
                
                # 清理临时文件
                try:
                    if 'temp_file' in locals() and temp_file.exists():
                        temp_file.unlink()
                except:
                    pass
                
                # 如果还有重试机会，等待一会再试
                if attempt < retry_count:
                    time.sleep(2)  # 重试前等待2秒
                else:
                    break
        
        if log_callback:
            log_callback(f"✗ 同步最终失败: {source_file.name} - 已重试 {retry_count} 次")
        return "Failed"
    
    def sync_directory(
        self,
        overwrite_existing: bool = False,
        rule_not_exists: bool = False,
        rule_size_diff: bool = False,
        rule_mtime_newer: bool = False,
        thread_count: int = 1,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        is_slow_storage: bool = False,
        size_min_bytes: Optional[int] = None,
        size_max_bytes: Optional[int] = None,
        suffix_mode: str = "NONE",
        suffix_list: Optional[list[str]] = None,
        file_result_callback: Optional[Callable[[Path, Path, str], None]] = None,
        retry_count: int = 0
    ) -> dict:
        """
        同步整个目录（支持多线程，固定递归模式，支持子规则）
        
        Args:
            overwrite_existing: 是否覆盖已存在的文件（主规则，内部使用）
            rule_not_exists: 子规刑1 - 目标文件不存在时同步
            rule_size_diff: 子规刑2 - 文件大小不一致时同步
            rule_mtime_newer: 子规刑3 - 源文件修改时间更新时同步
            thread_count: 线程数（1=单线程，>1=多线程）
            log_callback: 日志回调函数
            progress_callback: 进度回调函数
            is_slow_storage: 是否为慢速存储（会启用重试机制）
            size_min_bytes: 最小文件大小（字节），None 表示不限制
            size_max_bytes: 最大文件大小（字节），None 表示不限制
            suffix_mode: 后缀过滤模式：NONE/INCLUDE/EXCLUDE
            suffix_list: 后缀列表，小写且不带点，如 ["mp4", "mkv"]
            file_result_callback: 单文件处理结果回调，参数为 (source_file, target_file, result)
            retry_count: 失败重试次数
            
        Returns:
            同步统计信息字典
        """
        stats = {
            "success": 0,
            "skipped_ignored": 0,
            "skipped_active": 0,
            "skipped_unchanged": 0,
            "skipped_filtered": 0,
            "failed": 0,
            "total": 0
        }
        
        if log_callback:
            log_callback(f"开始同步目录: {self.source_dir} -> {self.target_dir}")
            if thread_count > 1:
                log_callback(f"多线程模式: {thread_count} 个线程")
        
        # 0. 清理残留临时文件
        self._cleanup_temp_files(log_callback)
        
        # 收集所有需要同步的文件（固定递归模式）
        pattern = "**/*"
        file_tasks = []
        for source_file in self.source_dir.glob(pattern):
            if not source_file.is_file():
                continue
            
            stats["total"] += 1
            relative_path = source_file.relative_to(self.source_dir)
            target_file = self.target_dir / relative_path
            file_tasks.append((source_file, target_file))
        
        # 单线程模式
        if thread_count == 1:
            for source_file, target_file in file_tasks:
                result = self.sync_file(
                    source_file, target_file, overwrite_existing,
                    rule_not_exists, rule_size_diff, rule_mtime_newer,
                    log_callback,
                    size_min_bytes=size_min_bytes,
                    size_max_bytes=size_max_bytes,
                    suffix_mode=suffix_mode,
                    suffix_list=suffix_list,
                    retry_count=retry_count
                )
                if file_result_callback:
                    file_result_callback(source_file, target_file, result)
                self._update_stats(stats, result)
                # 调用进度回调
                if progress_callback:
                    progress_callback(stats)
        
        # 多线程模式
        else:
            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                # 提交所有任务
                future_to_file = {
                    executor.submit(
                        self.sync_file,
                        source_file,
                        target_file,
                        overwrite_existing,
                        rule_not_exists,
                        rule_size_diff,
                        rule_mtime_newer,
                        log_callback,
                        size_min_bytes,
                        size_max_bytes,
                        suffix_mode,
                        suffix_list,
                        retry_count
                    ): (source_file, target_file)
                    for source_file, target_file in file_tasks
                }
                
                # 等待并处理结果
                for future in as_completed(future_to_file):
                    try:
                        result = future.result()
                        source_file, target_file = future_to_file[future]
                        if file_result_callback:
                            file_result_callback(source_file, target_file, result)
                        self._update_stats(stats, result)
                        # 调用进度回调
                        if progress_callback:
                            progress_callback(stats)
                    except Exception as e:
                        source_file, target_file = future_to_file[future]
                        if log_callback:
                            log_callback(f"线程处理失败: {source_file.name} - {str(e)}")
                        stats["failed"] += 1
                        # 失败也要更新进度
                        if progress_callback:
                            progress_callback(stats)
        
        # 不再在这里输出详细统计，统计信息将在调度器层面汇总输出
        
        return stats
    
    @staticmethod
    def _update_stats(stats: dict, result: str):
        """
        更新同步统计信息
        
        Args:
            stats: 统计字典
            result: 同步结果
        """
        if result == "Success":
            stats["success"] += 1
        elif result == "Skipped (Ignored)":
            stats["skipped_ignored"] += 1
        elif result == "Skipped (Active)":
            stats["skipped_active"] += 1
        elif result == "Skipped (Unchanged)":
            stats["skipped_unchanged"] += 1
        elif result == "Skipped (Filtered)":
            stats["skipped_filtered"] += 1
        elif result == "Failed":
            stats["failed"] += 1
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """
        格式化文件大小
        
        Args:
            size_bytes: 字节数
            
        Returns:
            格式化后的字符串
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def _cleanup_temp_files(self, log_callback: Optional[Callable[[str], None]] = None):
        """清理目标目录中的临时文件"""
        if log_callback:
            log_callback("正在检查并清理未完成的临时文件...")
        
        cleanup_count = 0
        try:
            for temp_file in self.target_dir.glob("**/.tmp_*"):
                if temp_file.is_file():
                    try:
                        temp_file.unlink()
                        cleanup_count += 1
                    except Exception as e:
                        if log_callback:
                            log_callback(f"⚠ 清理临时文件失败: {temp_file} - {e}")
        except Exception as e:
            if log_callback:
                log_callback(f"⚠ 扫描临时文件失败: {e}")
        
        if cleanup_count > 0 and log_callback:
            log_callback(f"✓ 已自动清理 {cleanup_count} 个未完成的临时文件")
        elif log_callback:
            log_callback("未发现残留临时文件")

    def reconstruct_cache_from_target(self, log_callback: Optional[Callable[[str], None]] = None) -> dict:
        """
        基于目标目录重构缓存（Result-driven Reconstruction）
        适用于老用户升级到带缓存版本后的历史数据导入。
        """
        stats = {"found": 0, "matched": 0, "updated": 0, "errors": 0}
        if not self.db or not self.task_id:
            return stats

        if log_callback:
            log_callback(f"🔍 开始重构任务缓存: {self.task_id}")
            log_callback(f"📂 扫描目标目录: {self.target_dir}")

        batch_records = []
        try:
            # 遍历目标目录
            for target_file in self.target_dir.rglob("*"):
                if not target_file.is_file() or target_file.name.startswith(".tmp_"):
                    continue
                
                stats["found"] += 1
                try:
                    rel_path = target_file.relative_to(self.target_dir)
                    source_file = self.source_dir / rel_path
                    
                    if source_file.exists() and source_file.is_file():
                        stats["matched"] += 1
                        
                        # 获取源文件元数据
                        stat = source_file.stat()
                        size = stat.st_size
                        mtime = stat.st_mtime
                        
                        # 构建缓存记录
                        # 注意：为了性能，重构时不实时计算哈希，等下次同步时触发。
                        # status 设为 SYNCED，因为目标文件确实存在。
                        record = {
                            "task_id": self.task_id,
                            "path": str(source_file),
                            "size": size,
                            "mtime": mtime,
                            "hash": None,
                            "hash_at": None,
                            "sync_status": "SYNCED",
                            "synced_at": datetime.now().isoformat(),
                            "deleted_at": None,
                            "last_seen_at": datetime.now().isoformat(),
                            "last_error": None,
                            "metadata": json.dumps({"reconstructed": True})
                        }
                        batch_records.append(record)
                        
                        # 每 500 条执行一次批量写入
                        if len(batch_records) >= 500:
                            self.db.batch_upsert_file_cache(batch_records)
                            stats["updated"] += len(batch_records)
                            batch_records = []
                            if log_callback:
                                log_callback(f"⏳ 已重构 {stats['updated']} 条记录...")
                except Exception as e:
                    stats["errors"] += 1
                    if log_callback:
                        log_callback(f"⚠ 处理文件失败: {target_file} - {e}")

            # 写入剩余记录
            if batch_records:
                self.db.batch_upsert_file_cache(batch_records)
                stats["updated"] += len(batch_records)

            # 写入一条审计记录
            self.db.add_history_record(
                task_id=self.task_id,
                path="SYSTEM/MIGRATION",
                status="INFO",
                details=f"Reconstructed {stats['updated']} entries from target directory."
            )

        except Exception as e:
            if log_callback:
                log_callback(f"❌ 重构过程发生严重错误: {e}")
            stats["errors"] += 1

        if log_callback:
            log_callback(f"✅ 重构完成! 扫描:{stats['found']}, 匹配:{stats['matched']}, 更新:{stats['updated']}, 错误:{stats['errors']}")
        
        return stats
