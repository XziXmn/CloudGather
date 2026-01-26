"""
STRM 文件智能删除保护机制
防止因网络故障等原因误删大量 .strm 文件
"""

import json
import logging
from pathlib import Path
from typing import Set, Dict


class StrmProtectionManager:
    """
    智能保护管理器
    
    防止误删大量 .strm 文件的保护机制：
    1. 设置删除阈值（threshold）：当待删除文件数超过此值时，启动保护
    2. 宽限扫描次数（grace_scans）：文件必须连续多次扫描都确认删除才真正删除
    3. 计数器系统：跟踪每个待删除文件的确认次数
    4. 回归检测：如果文件在后续扫描中重新出现，则重置其删除计数
    """
    
    def __init__(
        self,
        target_dir: Path,
        threshold: int = 100,
        grace_scans: int = 3,
        state_file: str = "strm_protection_state.json"
    ):
        """
        初始化保护管理器
        
        Args:
            target_dir: 目标目录（.strm 文件所在目录）
            threshold: 删除阈值，超过此数量启动保护机制
            grace_scans: 宽限扫描次数，文件必须连续确认这么多次才删除
            state_file: 状态文件名（保存在 target_dir 下）
        """
        self.target_dir = Path(target_dir)
        self.threshold = threshold
        self.grace_scans = grace_scans
        self.state_file = self.target_dir / state_file
        
        # 受保护的文件及其计数器：{相对路径: 确认次数}
        self.protected: Dict[str, int] = {}
        
        # 加载状态
        self._load_state()
    
    def _to_relative(self, abs_path: Path) -> str:
        """将绝对路径转换为相对于 target_dir 的相对路径"""
        try:
            return str(abs_path.relative_to(self.target_dir))
        except ValueError:
            # 如果路径不在 target_dir 下，返回绝对路径字符串
            return str(abs_path)
    
    def _to_absolute(self, rel_path: str) -> Path:
        """将相对路径转换为绝对路径"""
        return self.target_dir / rel_path
    
    def _load_state(self):
        """从文件加载状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.protected = data.get('protected', {})
                    logging.info(f"✅ 加载保护状态: {len(self.protected)} 个受保护文件")
            except Exception as e:
                logging.warning(f"⚠️ 加载保护状态失败: {e}")
                self.protected = {}
    
    def _save_state(self):
        """保存状态到文件"""
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'protected': self.protected,
                    'threshold': self.threshold,
                    'grace_scans': self.grace_scans
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"❌ 保存保护状态失败: {e}")
    
    def process(
        self,
        strm_to_delete: Set[Path],
        strm_present: Set[Path]
    ) -> Set[Path]:
        """
        处理待删除的 .strm 文件，返回现在可以删除的文件集合
        
        Args:
            strm_to_delete: 本次扫描发现的待删除文件集合（绝对路径）
            strm_present: 本次扫描发现的存在文件集合（绝对路径）
            
        Returns:
            现在可以安全删除的文件集合（绝对路径）
        """
        # 1. 恢复已回归的文件（重新出现在 present 中的文件）
        returned = 0
        for rel_path in list(self.protected.keys()):
            abs_path = self._to_absolute(rel_path)
            if abs_path in strm_present:
                del self.protected[rel_path]
                returned += 1
        
        if returned > 0:
            logging.info(f"✅ 恢复 {returned} 个文件的删除保护（文件已回归）")
            self._save_state()
        
        # 2. 如果待删除数量小于阈值，直接删除（不启动保护）
        if len(strm_to_delete) < self.threshold:
            if len(strm_to_delete) > 0:
                logging.info(f"✅ 待删除 {len(strm_to_delete)} 个文件（小于阈值 {self.threshold}，直接删除）")
            return strm_to_delete
        
        # 3. 启动保护机制：记录或更新计数
        logging.warning(
            f"⚠️ 待删除 {len(strm_to_delete)} 个文件（超过阈值 {self.threshold}），启动保护机制"
        )
        
        for file_path in strm_to_delete:
            rel_path = self._to_relative(file_path)
            # 增加计数
            self.protected[rel_path] = self.protected.get(rel_path, 0) + 1
        
        # 4. 只删除连续 grace_scans 次都确认要删的文件
        ready_rel = {
            rel_path for rel_path, count in self.protected.items()
            if count >= self.grace_scans
        }
        
        ready = {self._to_absolute(rel_path) for rel_path in ready_rel}
        
        # 从保护列表中移除已确认删除的文件
        for rel_path in ready_rel:
            del self.protected[rel_path]
        
        # 保存状态
        self._save_state()
        
        if len(ready) > 0:
            logging.info(
                f"✅ 经过 {self.grace_scans} 次确认，现在可以删除 {len(ready)} 个文件"
            )
        else:
            logging.info(
                f"⏳ 还有 {len(self.protected)} 个文件处于保护期，需要继续确认"
            )
        
        return ready
    
    def get_protection_stats(self) -> Dict[str, int]:
        """
        获取保护统计信息
        
        Returns:
            统计信息字典，包含：
            - total: 总受保护文件数
            - by_count: 按确认次数分组的统计
        """
        stats = {
            'total': len(self.protected),
            'by_count': {}
        }
        
        for count in self.protected.values():
            stats['by_count'][count] = stats['by_count'].get(count, 0) + 1
        
        return stats
    
    def reset(self):
        """重置保护状态（清空所有计数）"""
        self.protected.clear()
        self._save_state()
        logging.info("✅ 已重置保护状态")
    
    def force_approve_all(self) -> Set[Path]:
        """
        强制批准所有待删除文件（慎用！）
        
        Returns:
            所有受保护文件的集合（绝对路径）
        """
        all_files = {self._to_absolute(rel_path) for rel_path in self.protected.keys()}
        self.protected.clear()
        self._save_state()
        logging.warning(f"⚠️ 强制批准删除 {len(all_files)} 个文件")
        return all_files
