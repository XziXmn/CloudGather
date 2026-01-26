"""
数据库管理模块
使用 SQLite 存储删除队列和目录树等大数据结构
"""

import sqlite3
import json
import threading
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
from contextlib import contextmanager


class Database:
    """SQLite 数据库管理类"""
    
    def __init__(self, db_path: str = "config/cloudgather.db"):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = Path(db_path)
        self._local = threading.local()
        
        # 确保数据库目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库结构
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """获取线程本地的数据库连接（上下文管理器）"""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self._local.conn.row_factory = sqlite3.Row
        
        try:
            yield self._local.conn
        except Exception:
            self._local.conn.rollback()
            raise
    
    def _init_database(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 创建删除队列表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS delete_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    source_path TEXT NOT NULL UNIQUE,
                    delete_at TEXT NOT NULL,
                    delete_parent INTEGER DEFAULT 0,
                    time_base TEXT DEFAULT 'SYNC_COMPLETE',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delete_queue_task_id 
                ON delete_queue(task_id)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delete_queue_delete_at 
                ON delete_queue(delete_at)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_delete_queue_source_path 
                ON delete_queue(source_path)
            """)
            
            # 创建目录树表（为未来扩展准备）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS directory_tree (
                    path TEXT PRIMARY KEY,
                    parent_path TEXT,
                    is_directory INTEGER DEFAULT 1,
                    size INTEGER DEFAULT 0,
                    mtime TEXT,
                    synced_at TEXT,
                    task_id TEXT,
                    metadata TEXT
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_directory_tree_parent 
                ON directory_tree(parent_path)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_directory_tree_task_id 
                ON directory_tree(task_id)
            """)
            
            # 创建配置表（存储迁移状态等元数据）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
    
    # ==================== 删除队列操作 ====================
    
    def add_delete_record(self, task_id: str, source_path: str, delete_at: str,
                         delete_parent: bool = False, time_base: str = "SYNC_COMPLETE"):
        """
        添加或更新删除记录
        
        Args:
            task_id: 任务ID
            source_path: 源文件路径
            delete_at: 删除时间（ISO格式）
            delete_parent: 是否删除上级目录
            time_base: 时间基准类型
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO delete_queue (task_id, source_path, delete_at, delete_parent, time_base)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    task_id = excluded.task_id,
                    delete_at = excluded.delete_at,
                    delete_parent = excluded.delete_parent,
                    time_base = excluded.time_base,
                    updated_at = CURRENT_TIMESTAMP
            """, (task_id, source_path, delete_at, int(delete_parent), time_base))
            conn.commit()
    
    def get_expired_records(self, task_id: str, current_time: str) -> List[Dict[str, Any]]:
        """
        获取指定任务的已到期删除记录
        
        Args:
            task_id: 任务ID
            current_time: 当前时间（ISO格式）
            
        Returns:
            到期记录列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, task_id, source_path, delete_at, delete_parent, time_base
                FROM delete_queue
                WHERE task_id = ? AND delete_at <= ?
                ORDER BY delete_at ASC
            """, (task_id, current_time))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_pending_records(self, task_id: str, current_time: str, 
                           base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取指定任务的未到期删除记录
        
        Args:
            task_id: 任务ID
            current_time: 当前时间（ISO格式）
            base_dir: 可选的目录过滤（检查记录是否在该目录下）
            
        Returns:
            未到期记录列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if base_dir:
                # 使用 LIKE 模糊匹配子目录
                cursor.execute("""
                    SELECT id, task_id, source_path, delete_at, delete_parent, time_base
                    FROM delete_queue
                    WHERE task_id = ? AND delete_at > ? AND source_path LIKE ?
                    ORDER BY delete_at ASC
                """, (task_id, current_time, f"{base_dir}%"))
            else:
                cursor.execute("""
                    SELECT id, task_id, source_path, delete_at, delete_parent, time_base
                    FROM delete_queue
                    WHERE task_id = ? AND delete_at > ?
                    ORDER BY delete_at ASC
                """, (task_id, current_time))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def remove_delete_record(self, source_path: str):
        """
        删除指定的删除记录
        
        Args:
            source_path: 源文件路径
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM delete_queue WHERE source_path = ?", (source_path,))
            conn.commit()
    
    def remove_delete_records_by_id(self, record_ids: List[int]):
        """
        批量删除删除记录
        
        Args:
            record_ids: 记录ID列表
        """
        if not record_ids:
            return
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(record_ids))
            cursor.execute(f"DELETE FROM delete_queue WHERE id IN ({placeholders})", record_ids)
            conn.commit()
    
    def get_all_delete_records(self, task_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取所有删除记录
        
        Args:
            task_id: 可选的任务ID过滤
            
        Returns:
            删除记录列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if task_id:
                cursor.execute("""
                    SELECT id, task_id, source_path, delete_at, delete_parent, time_base
                    FROM delete_queue
                    WHERE task_id = ?
                    ORDER BY delete_at ASC
                """, (task_id,))
            else:
                cursor.execute("""
                    SELECT id, task_id, source_path, delete_at, delete_parent, time_base
                    FROM delete_queue
                    ORDER BY delete_at ASC
                """)
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_delete_queue_count(self, task_id: Optional[str] = None) -> int:
        """
        获取删除队列中的记录数量
        
        Args:
            task_id: 可选的任务ID过滤
            
        Returns:
            记录数量
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if task_id:
                cursor.execute("SELECT COUNT(*) FROM delete_queue WHERE task_id = ?", (task_id,))
            else:
                cursor.execute("SELECT COUNT(*) FROM delete_queue")
            
            return cursor.fetchone()[0]
    
    # ==================== 配置操作 ====================
    
    def set_config(self, key: str, value: str):
        """设置配置项"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO config (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, value))
            conn.commit()
    
    def get_config(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取配置项"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
    
    # ==================== 迁移操作 ====================
    
    def migrate_from_json(self, delete_queue: List[Dict[str, Any]]) -> int:
        """
        从 JSON 格式的删除队列迁移到数据库
        
        Args:
            delete_queue: JSON 格式的删除队列数据
            
        Returns:
            迁移的记录数量
        """
        if not delete_queue:
            return 0
        
        migrated_count = 0
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for record in delete_queue:
                try:
                    task_id = record.get('task_id')
                    source_path = record.get('source_path')
                    delete_at = record.get('delete_at')
                    delete_parent = record.get('delete_parent', False)
                    time_base = record.get('time_base', 'SYNC_COMPLETE')
                    
                    if not all([task_id, source_path, delete_at]):
                        continue
                    
                    cursor.execute("""
                        INSERT OR IGNORE INTO delete_queue 
                        (task_id, source_path, delete_at, delete_parent, time_base)
                        VALUES (?, ?, ?, ?, ?)
                    """, (task_id, source_path, delete_at, int(delete_parent), time_base))
                    
                    if cursor.rowcount > 0:
                        migrated_count += 1
                
                except Exception as e:
                    print(f"迁移记录失败: {record.get('source_path')} - {e}")
                    continue
            
            conn.commit()
        
        return migrated_count
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, 'conn'):
            self._local.conn.close()
            delattr(self._local, 'conn')
