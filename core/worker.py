"""
NAS 文件同步核心模块
提供原子化写入、静默期检测、垃圾过滤等功能
"""

import os
import time
import hashlib
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple


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
    
    def calculate_md5(
        self, 
        file_path: Path, 
        log_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        计算文件 MD5 值
        
        Args:
            file_path: 文件路径
            log_callback: 日志回调函数
            
        Returns:
            MD5 哈希值（十六进制字符串）
        """
        md5_hash = hashlib.md5()
        file_size = file_path.stat().st_size
        bytes_read = 0
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5_hash.update(chunk)
                bytes_read += len(chunk)
                
                # 每读取 10MB 报告一次进度
                if log_callback and bytes_read % (10 * 1024 * 1024) == 0:
                    progress = (bytes_read / file_size * 100) if file_size > 0 else 0
                    log_callback(f"计算 MD5: {file_path.name} ({progress:.1f}%)")
        
        return md5_hash.hexdigest()
    
    def sync_file(
        self,
        source_file: Path,
        target_file: Path,
        verify_md5: bool = False,
        log_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """
        同步单个文件（原子化写入）
        
        Args:
            source_file: 源文件路径
            target_file: 目标文件路径
            verify_md5: 是否进行 MD5 校验
            log_callback: 日志回调函数
            
        Returns:
            同步状态: "Success", "Skipped (Ignored)", "Skipped (Active)", "Failed"
        """
        try:
            # 1. 垃圾过滤
            if self.should_ignore(source_file):
                if log_callback:
                    log_callback(f"已忽略: {source_file.name} (垃圾文件)")
                return "Skipped (Ignored)"
            
            # 2. 静默期检测
            is_stable, file_size = self.check_file_stability(source_file, log_callback)
            if not is_stable:
                if log_callback:
                    log_callback(f"已跳过: {source_file.name} (文件活动中)")
                return "Skipped (Active)"
            
            # 3. 准备临时文件路径
            target_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = target_file.parent / f".tmp_{target_file.name}"
            
            # 4. 复制文件
            if log_callback:
                log_callback(f"开始复制: {source_file.name} ({self._format_size(file_size)})")
            
            # 使用 shutil.copy2 保留元数据
            shutil.copy2(source_file, temp_file)
            
            if log_callback:
                log_callback(f"复制完成: {source_file.name}")
            
            # 5. 校验文件大小
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
            
            # 6. MD5 校验（可选）
            if verify_md5:
                if log_callback:
                    log_callback(f"开始 MD5 校验: {source_file.name}")
                
                source_md5 = self.calculate_md5(source_file, log_callback)
                temp_md5 = self.calculate_md5(temp_file, log_callback)
                
                if source_md5 != temp_md5:
                    if log_callback:
                        log_callback(
                            f"MD5 校验失败: {source_file.name} "
                            f"(源: {source_md5}, 目标: {temp_md5})"
                        )
                    temp_file.unlink()
                    return "Failed"
                
                if log_callback:
                    log_callback(f"MD5 校验通过: {source_file.name}")
            
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
        recursive: bool = True,
        verify_md5: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> dict:
        """
        同步整个目录
        
        Args:
            recursive: 是否递归同步子目录
            verify_md5: 是否进行 MD5 校验
            log_callback: 日志回调函数
            
        Returns:
            同步统计信息字典
        """
        stats = {
            "success": 0,
            "skipped_ignored": 0,
            "skipped_active": 0,
            "failed": 0,
            "total": 0
        }
        
        if log_callback:
            log_callback(f"开始同步目录: {self.source_dir} -> {self.target_dir}")
        
        # 遍历源目录并预先统计文件数量
        pattern = "**/*" if recursive else "*"
        source_files = [f for f in self.source_dir.glob(pattern) if f.is_file()]
        stats["total"] = len(source_files)

        if progress_callback:
            progress_callback(0, stats["total"], "")

        for index, source_file in enumerate(source_files, start=1):
            
            # 计算相对路径
            relative_path = source_file.relative_to(self.source_dir)
            target_file = self.target_dir / relative_path
            
            # 同步文件
            result = self.sync_file(source_file, target_file, verify_md5, log_callback)

            if progress_callback:
                progress_callback(index, stats["total"], source_file.name)
            
            # 更新统计
            if result == "Success":
                stats["success"] += 1
            elif result == "Skipped (Ignored)":
                stats["skipped_ignored"] += 1
            elif result == "Skipped (Active)":
                stats["skipped_active"] += 1
            elif result == "Failed":
                stats["failed"] += 1
        
        if log_callback:
            log_callback(
                f"\n同步完成！"
                f"\n  总文件数: {stats['total']}"
                f"\n  成功: {stats['success']}"
                f"\n  跳过(垃圾): {stats['skipped_ignored']}"
                f"\n  跳过(活动): {stats['skipped_active']}"
                f"\n  失败: {stats['failed']}"
            )
        
        return stats
    
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
