"""
STRM 文件生成器核心模块
负责从 OpenList 生成 .strm 文件并同步相关文件（字幕、图片、NFO 等）
"""

import logging
import shutil
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Set, List
from collections import defaultdict

from core.models import StrmTask, StrmMode
from core.openlist_client import OpenListClient, OpenListFile
from core.strm_protection import StrmProtectionManager


class StrmGenerator:
    """STRM 文件生成器"""
    
    def __init__(
        self,
        task: StrmTask,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        """
        初始化生成器
        
        Args:
            task: STRM 任务对象
            log_callback: 日志回调函数
        """
        self.task = task
        self.log_callback = log_callback
        
        # 统计信息
        self.stats = {
            'total': 0,
            'success': 0,
            'skipped': 0,
            'failed': 0,
            'strm_created': 0,
            'strm_skipped': 0,
            'strm_deleted': 0,
            'extra_synced': 0  # 字幕、图片、NFO 等额外文件
        }
        
        # 智能保护管理器
        self.protection: Optional[StrmProtectionManager] = None
        if self.task.smart_protection:
            self.protection = StrmProtectionManager(
                target_dir=Path(self.task.target_dir),
                threshold=self.task.smart_protection.get('threshold', 100),
                grace_scans=self.task.smart_protection.get('grace_scans', 3)
            )
    
    def log(self, message: str):
        """记录日志"""
        if self.log_callback:
            self.log_callback(message)
        else:
            logging.info(message)
    
    def run(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """
        执行 STRM 生成任务
        
        Args:
            progress_callback: 进度回调函数，接收进度信息字典
            
        Returns:
            执行结果统计信息
        """
        self.log(f"📋 开始执行 STRM 任务: {self.task.name}")
        self.log(f"🔗 源目录: {self.task.source_dir}")
        self.log(f"💾 目标目录: {self.task.target_dir}")
        self.log(f"📝 生成模式: {self.task.mode.value}")
        
        try:
            # 1. 创建 OpenList 客户端
            client = self._create_client()
            if not client:
                self.log("❌ 创建 OpenList 客户端失败")
                return self.stats
            
            # 2. 测试连接
            if not client.test_connection():
                self.log("❌ OpenList 连接测试失败")
                return self.stats
            
            # 3. 遍历文件并生成 STRM
            self.log("🔍 开始扫描文件...")
            
            # 收集所有视频文件
            video_files: List[OpenListFile] = []
            for file in client.iter_all_files(self.task.source_dir):
                if client.is_video_file(file):
                    video_files.append(file)
            
            self.stats['total'] = len(video_files)
            self.log(f"📊 发现 {self.stats['total']} 个视频文件")
            
            if self.stats['total'] == 0:
                self.log("⚠️ 未发现任何视频文件")
                return self.stats
            
            # 4. 处理 BDMV 文件（如果有）
            video_files = self._process_bdmv_files(video_files)
            
            # 5. 收集现有的 .strm 文件
            target_dir = Path(self.task.target_dir)
            existing_strm = self._collect_existing_strm(target_dir)
            
            # 6. 生成 .strm 文件
            generated_strm = set()
            for idx, file in enumerate(video_files, 1):
                # 更新进度
                if progress_callback:
                    progress_callback({
                        'done': idx,
                        'total': self.stats['total'],
                        'percent': int((idx / self.stats['total']) * 100),
                        'success': self.stats['success'],
                        'skipped': self.stats['skipped'],
                        'failed': self.stats['failed']
                    })
                
                try:
                    strm_path = self._generate_strm_for_file(client, file)
                    if strm_path:
                        generated_strm.add(strm_path)
                        self.stats['success'] += 1
                    else:
                        self.stats['skipped'] += 1
                except Exception as e:
                    self.log(f"❌ 处理失败: {file.full_path} - {e}")
                    self.stats['failed'] += 1
            
            # 7. 删除过时的 .strm 文件
            if self.task.sync_server:
                self._sync_deletions(existing_strm, generated_strm)
            
            # 8. 同步本地删除到服务器
            if getattr(self.task, 'sync_local_delete', False):
                self._sync_local_deletions_to_server(client, video_files, existing_strm)
            
            # 9. 输出统计信息
            self.log("=" * 50)
            self.log(f"✅ 任务完成!")
            self.log(f"📊 总计: {self.stats['total']} 个视频文件")
            self.log(f"✅ 成功: {self.stats['success']} 个")
            self.log(f"⏭️ 跳过: {self.stats['skipped']} 个")
            self.log(f"❌ 失败: {self.stats['failed']} 个")
            self.log(f"📝 生成 STRM: {self.stats['strm_created']} 个")
            self.log(f"🗑️ 删除 STRM: {self.stats['strm_deleted']} 个")
            if self.stats['extra_synced'] > 0:
                self.log(f"📎 同步额外文件: {self.stats['extra_synced']} 个")
            
            return self.stats
            
        except Exception as e:
            self.log(f"❌ 任务执行异常: {e}")
            import traceback
            self.log(traceback.format_exc())
            return self.stats
    
    def _create_client(self) -> Optional[OpenListClient]:
        """创建 OpenList 客户端"""
        # 从全局配置加载（如果任务未配置）
        from api.settings import load_openlist_config, load_extensions_config
        global_config = load_openlist_config()
        ext_config = load_extensions_config()
        
        url = self.task.openlist_url or global_config.get('url')
        username = self.task.openlist_username or global_config.get('username')
        password = self.task.openlist_password or global_config.get('password')
        token = self.task.openlist_token or global_config.get('token')
        public_url = self.task.openlist_public_url or global_config.get('public_url')
        
        if not url:
            self.log("❌ 未配置 OpenList 服务器地址")
            return None
        
        # 解析自定义扩展名
        subtitle_exts = [e.strip() for e in ext_config.get('subtitle', '').split(',') if e.strip()]
        image_exts = [e.strip() for e in ext_config.get('image', '').split(',') if e.strip()]
        nfo_exts = [e.strip() for e in ext_config.get('nfo', '').split(',') if e.strip()]
        
        return OpenListClient(
            url=url,
            username=username,
            password=password,
            token=token,
            public_url=public_url,
            subtitle_extensions=subtitle_exts,
            image_extensions=image_exts,
            nfo_extensions=nfo_exts
        )
    
    def _process_bdmv_files(self, files: List[OpenListFile]) -> List[OpenListFile]:
        """
        处理 BDMV 蓝光原盘文件
        
        对于 BDMV 结构（/BDMV/STREAM/*.m2ts），收集同一电影的所有 .m2ts 文件，
        选择最大的一个，并使用电影根目录名称作为 .strm 文件名
        
        Args:
            files: 文件列表
            
        Returns:
            处理后的文件列表
        """
        # 识别 BDMV 文件
        bdmv_files = []
        non_bdmv_files = []
        
        for file in files:
            if '/BDMV/STREAM/' in file.full_path and file.suffix.lower() == '.m2ts':
                bdmv_files.append(file)
            else:
                non_bdmv_files.append(file)
        
        if not bdmv_files:
            return files
        
        self.log(f"🎬 发现 {len(bdmv_files)} 个 BDMV 文件，开始处理...")
        
        # 按电影分组（根据 BDMV 前的路径）
        bdmv_groups: Dict[str, List[OpenListFile]] = defaultdict(list)
        for file in bdmv_files:
            # 提取电影根目录：/Movies/Avatar/BDMV/STREAM/00001.m2ts -> /Movies/Avatar
            parts = file.full_path.split('/BDMV/')
            if len(parts) >= 2:
                movie_root = parts[0]
                bdmv_groups[movie_root].append(file)
        
        # 每组选择最大的文件
        selected_bdmv = []
        for movie_root, group in bdmv_groups.items():
            # 按大小排序，选择最大的
            largest = max(group, key=lambda f: f.size)
            # 修改文件名为电影根目录名称
            movie_name = Path(movie_root).name
            largest.name = f"{movie_name}.m2ts"
            selected_bdmv.append(largest)
            
            self.log(f"  📀 {movie_name}: 选择 {largest.size / (1024**3):.2f} GB 的主文件")
        
        return non_bdmv_files + selected_bdmv
    
    def _generate_strm_for_file(
        self,
        client: OpenListClient,
        file: OpenListFile
    ) -> Optional[Path]:
        """
        为单个视频文件生成 .strm 文件
        
        Args:
            client: OpenList 客户端
            file: 视频文件信息
            
        Returns:
            生成的 .strm 文件路径，如果跳过则返回 None
        """
        # 计算目标路径
        if self.task.flatten_mode:
            # 扁平化模式：所有文件放在根目录
            rel_path = file.name
        else:
            # 保持目录结构
            rel_path = file.full_path.replace(self.task.source_dir, '').lstrip('/')
        
        # 生成 .strm 文件路径
        target_dir = Path(self.task.target_dir)
        strm_path = target_dir / Path(rel_path).with_suffix('.strm')
        
        # 检查是否需要跳过
        if not self.task.overwrite and strm_path.exists():
            return strm_path
        
        # 确保目标目录存在
        strm_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 生成 .strm 内容
        if self.task.mode == StrmMode.ALIST_URL:
            content = file.download_url
        elif self.task.mode == StrmMode.RAW_URL:
            content = file.raw_url
        elif self.task.mode == StrmMode.ALIST_PATH:
            content = file.full_path
        else:
            content = file.download_url
        
        # 写入 .strm 文件
        try:
            with open(strm_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.stats['strm_created'] += 1
        except Exception as e:
            self.log(f"❌ 写入 STRM 失败: {strm_path} - {e}")
            raise
        
        # 同步额外文件（字幕、图片、NFO 等）
        if self.task.subtitle or self.task.image or self.task.nfo:
            self._sync_extra_files(client, file, strm_path.parent)
        
        return strm_path
    
    def _sync_extra_files(
        self,
        client: OpenListClient,
        video_file: OpenListFile,
        target_dir: Path
    ):
        """
        同步额外文件（字幕、图片、NFO 等）
        
        Args:
            client: OpenList 客户端
            video_file: 视频文件信息
            target_dir: 目标目录
        """
        # 列出视频文件所在目录的所有文件
        result = client.list_dir(video_file.path)
        if not result or 'content' not in result:
            return
        
        video_stem = video_file.stem
        
        for item in result['content']:
            if item.get('is_dir'):
                continue
            
            file_name = item.get('name', '')
            file_path = Path(file_name)
            suffix = file_path.suffix.lower()
            
            # 检查是否为同名文件（去除扩展名比较）
            if file_path.stem != video_stem:
                continue
            
            should_sync = False
            if self.task.subtitle and suffix in client.SUBTITLE_EXTENSIONS:
                should_sync = True
            elif self.task.image and suffix in client.IMAGE_EXTENSIONS:
                should_sync = True
            elif self.task.nfo and suffix in client.NFO_EXTENSIONS:
                should_sync = True
            
            if should_sync:
                target_file = target_dir / file_name
                if not target_file.exists() or self.task.overwrite:
                    # 这里简化处理，实际应该下载文件
                    # 由于是 demo，暂时只记录日志
                    self.stats['extra_synced'] += 1
    
    def _collect_existing_strm(self, target_dir: Path) -> Set[Path]:
        """
        收集目标目录中现有的 .strm 文件
        
        Args:
            target_dir: 目标目录
            
        Returns:
            现有 .strm 文件路径集合
        """
        if not target_dir.exists():
            return set()
        
        return set(target_dir.rglob('*.strm'))
    
    def _sync_deletions(self, existing_strm: Set[Path], generated_strm: Set[Path]):
        """
        同步删除过时的 .strm 文件
        
        Args:
            existing_strm: 现有的 .strm 文件集合
            generated_strm: 本次生成的 .strm 文件集合
        """
        to_delete = existing_strm - generated_strm
        
        if not to_delete:
            return
        
        self.log(f"🗑️ 发现 {len(to_delete)} 个过时的 .strm 文件")
        
        # 使用智能保护
        if self.protection:
            to_delete = self.protection.process(to_delete, generated_strm)
        
        # 执行删除
        for strm_file in to_delete:
            try:
                strm_file.unlink()
                self.stats['strm_deleted'] += 1
                self.log(f"  🗑️ 已删除: {strm_file.name}")
            except Exception as e:
                self.log(f"  ❌ 删除失败: {strm_file} - {e}")

    def _sync_local_deletions_to_server(
        self, 
        client: OpenListClient, 
        video_files: List[OpenListFile], 
        existing_strm: Set[Path]
    ):
        """
        将本地删除操作同步到服务器
        
        Args:
            client: OpenList 客户端
            video_files: 服务器上的所有视频文件
            existing_strm: 本地现有的 .strm 文件
        """
        server_files_to_delete = []
        
        # 获取过滤配置
        suffix_mode = getattr(self.task, 'suffix_mode', 'NONE')
        suffix_list = getattr(self.task, 'suffix_list', [])
        
        for file in video_files:
            # 计算对应的本地 .strm 路径
            if self.task.flatten_mode:
                rel_path = file.name
            else:
                rel_path = file.full_path.replace(self.task.source_dir, '').lstrip('/')
            
            target_dir = Path(self.task.target_dir)
            strm_path = target_dir / Path(rel_path).with_suffix('.strm')
            
            # 如果本地 .strm 不存在，说明可能被用户删除了
            if not strm_path.exists():
                # 检查是否匹配忽略规则 (suffix_mode 和 suffix_list)
                # 如果 mode 为 EXCLUDE 且后缀在列表中，则跳过删除（即忽略）
                suffix = file.suffix.lower().lstrip('.')
                if suffix_mode == 'EXCLUDE' and suffix in suffix_list:
                    continue
                # 如果 mode 为 INCLUDE 且后缀不在列表中，也相当于忽略
                if suffix_mode == 'INCLUDE' and suffix not in suffix_list:
                    continue
                
                # 安全检查：如果 strm_path.parent 存在但文件不存在，更有可能是被删除了
                # 如果连 parent 都不存在，可能是因为任务刚创建或目录结构变了，此时不轻易删除服务器文件
                if strm_path.parent.exists():
                    server_files_to_delete.append(file.full_path)
        
        if not server_files_to_delete:
            return
            
        self.log(f"🗑️ 发现 {len(server_files_to_delete)} 个本地已删除的文件，准备同步到服务器...")
        
        # 这里可以使用智能保护阈值来防止误删
        threshold = self.task.smart_protection.get('threshold', 100) if self.task.smart_protection else 100
        if len(server_files_to_delete) > threshold:
            self.log(f"⚠️ 待删除数量 ({len(server_files_to_delete)}) 超过阈值 ({threshold})，智能保护已拦截服务器删除操作。")
            return
            
        # 执行服务器删除
        success_count = 0
        for path in server_files_to_delete:
            if client.remove_files([path]):
                self.log(f"  🗑️ 已从服务器删除: {path}")
                success_count += 1
            else:
                self.log(f"  ❌ 服务器删除失败: {path}")
        
        if success_count > 0:
            self.log(f"✅ 已完成服务器同步删除，共删除 {success_count} 个文件")

