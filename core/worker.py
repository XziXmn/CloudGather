"""
NAS 文件同步核心模块
提供原子化写入、静默期检测、垃圾过滤等功能
"""

import os
import time
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple
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
    
    def __init__(self, source_dir: str, target_dir: str):
        """
        初始化文件同步器
        
        Args:
            source_dir: 源目录路径
            target_dir: 目标目录路径
        """
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        
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
        智能判断是否需要同步文件（支持子规则）
        
        Args:
            source_file: 源文件路径
            target_file: 目标文件路径
            overwrite_existing: 是否覆盖已存在的文件（主规则，内部使用）
            rule_not_exists: 子规刑1 - 目标文件不存在时同步
            rule_size_diff: 子规刑2 - 文件大小不一致时同步
            rule_mtime_newer: 子规刑3 - 源文件修改时间更新时同步
            
        Returns:
            (should_sync, reason) - 是否需要同步及原因
        """
        # 目标文件不存在
        if not target_file.exists():
            # 如果子规刑1启用，则同步
            if rule_not_exists:
                return True, "target_not_exists (rule)"
            # 如果没有启用任何子规则，但是覆盖模式，也同步
            if overwrite_existing:
                return True, "target_not_exists (overwrite_mode)"
            # 否则跳过
            return False, "target_not_exists (no_rule)"
        
        # 目标文件已存在，检查其他子规则
        try:
            source_stat = source_file.stat()
            target_stat = target_file.stat()
            
            # 子规刑2: 大小不一致
            if rule_size_diff and source_stat.st_size != target_stat.st_size:
                return True, "size_diff (rule)"
            
            # 子规刑3: 修改时间比较（源文件更新）
            if rule_mtime_newer and source_stat.st_mtime > target_stat.st_mtime:
                return True, "mtime_newer (rule)"
            
            # 如果是覆盖模式，直接同步
            if overwrite_existing:
                return True, "overwrite_mode"
            
            # 文件相同，无需同步
            return False, "unchanged"
            
        except Exception as e:
            # 出错时默认需要同步
            return True, f"check_error: {str(e)}"
    
    def sync_file(
        self,
        source_file: Path,
        target_file: Path,
        overwrite_existing: bool = False,
        rule_not_exists: bool = False,
        rule_size_diff: bool = False,
        rule_mtime_newer: bool = False,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        同步单个文件（原子化写入，支持子规则）
        
        Args:
            source_file: 源文件路径
            target_file: 目标文件路径
            overwrite_existing: 是否覆盖已存在的文件（主规则，内部使用）
            rule_not_exists: 子规刑1 - 目标文件不存在时同步
            rule_size_diff: 子规刑2 - 文件大小不一致时同步
            rule_mtime_newer: 子规刑3 - 源文件修改时间更新时同步
            log_callback: 日志回调函数
            
        Returns:
            同步状态: "Success", "Skipped (Ignored)", "Skipped (Active)", "Skipped (Unchanged)", "Failed"
        """
        try:
            # 1. 垃圾过滤
            if self.should_ignore(source_file):
                if log_callback:
                    log_callback(f"已忽略: {source_file.name} (垃圾文件)")
                return "Skipped (Ignored)"
            
            # 2. 智能判断是否需要同步（传入子规则参数）
            should_sync, reason = self.should_sync_file(
                source_file, target_file, overwrite_existing,
                rule_not_exists, rule_size_diff, rule_mtime_newer
            )
            if not should_sync:
                if log_callback:
                    if reason == "unchanged":
                        log_callback(f"已跳过: {source_file.name} (文件未变更)")
                    else:
                        log_callback(f"已跳过: {source_file.name} ({reason})")
                return "Skipped (Unchanged)"
            
            # 3. 静默期检测
            is_stable, file_size = self.check_file_stability(source_file, log_callback)
            if not is_stable:
                if log_callback:
                    log_callback(f"已跳过: {source_file.name} (文件活动中)")
                return "Skipped (Active)"
            
            # 4. 准备临时文件路径
            target_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = target_file.parent / f".tmp_{target_file.name}"
            
            # 5. 复制文件
            if log_callback:
                log_callback(f"开始复制: {source_file.name} ({self._format_size(file_size)})")
            
            # 使用 shutil.copy2 保留元数据
            shutil.copy2(source_file, temp_file)
            
            if log_callback:
                log_callback(f"复制完成: {source_file.name}")
            
            # 6. 校验文件大小
            temp_size = temp_file.stat().st_size
            if temp_size != file_size:
                if log_callback:
                    log_callback(
                        f"大小校验失败: {source_file.name} "
                        f"(期望: {self._format_size(file_size)}, "
                        f"实际: {self._format_size(temp_size)})"
                    )
                temp_file.unlink()
                return "Failed"
            
            # 7. 原子化重命名
            if target_file.exists():
                target_file.unlink()
            
            os.rename(temp_file, target_file)
            
            if log_callback:
                log_callback(f"✓ 同步成功: {source_file.name}")
            
            return "Success"
            
        except Exception as e:
            if log_callback:
                log_callback(f"✗ 同步失败: {source_file.name} - {str(e)}")
            
            # 清理临时文件
            try:
                if 'temp_file' in locals() and temp_file.exists():
                    temp_file.unlink()
            except:
                pass
            
            return "Failed"
    
    def sync_directory(
        self,
        overwrite_existing: bool = False,
        rule_not_exists: bool = False,
        rule_size_diff: bool = False,
        rule_mtime_newer: bool = False,
        thread_count: int = 1,
        log_callback: Optional[Callable[[str], None]] = None
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
            
        Returns:
            同步统计信息字典
        """
        stats = {
            "success": 0,
            "skipped_ignored": 0,
            "skipped_active": 0,
            "skipped_unchanged": 0,
            "failed": 0,
            "total": 0
        }
        
        if log_callback:
            log_callback(f"开始同步目录: {self.source_dir} -> {self.target_dir}")
            if thread_count > 1:
                log_callback(f"多线程模式: {thread_count} 个线程")
        
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
                    log_callback
                )
                self._update_stats(stats, result)
        
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
                        log_callback
                    ): (source_file, target_file)
                    for source_file, target_file in file_tasks
                }
                
                # 等待并处理结果
                for future in as_completed(future_to_file):
                    try:
                        result = future.result()
                        self._update_stats(stats, result)
                    except Exception as e:
                        source_file, target_file = future_to_file[future]
                        if log_callback:
                            log_callback(f"线程处理失败: {source_file.name} - {str(e)}")
                        stats["failed"] += 1
        
        if log_callback:
            log_callback(
                f"\n同步完成！"
                f"\n  总文件数: {stats['total']}"
                f"\n  成功: {stats['success']}"
                f"\n  跳过(垃圾): {stats['skipped_ignored']}"
                f"\n  跳过(活动): {stats['skipped_active']}"
                f"\n  跳过(未变更): {stats['skipped_unchanged']}"
                f"\n  失败: {stats['failed']}"
            )
        
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
