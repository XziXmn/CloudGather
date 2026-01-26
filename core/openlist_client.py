"""
OpenList (原 AList) 客户端
封装 OpenList API 调用
"""

import logging
import requests
from typing import Optional, Dict, Any, List, AsyncIterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OpenListFile:
    """OpenList 文件信息"""
    name: str
    path: str
    full_path: str
    is_dir: bool
    size: int
    modified: str
    sign: str = ""
    raw_url: str = ""
    download_url: str = ""
    
    @property
    def suffix(self) -> str:
        """获取文件扩展名（含点，如 .mp4）"""
        return Path(self.name).suffix
    
    @property
    def stem(self) -> str:
        """获取文件名（不含扩展名）"""
        return Path(self.name).stem


class OpenListClient:
    """OpenList API 客户端"""
    
    # 视频文件扩展名
    VIDEO_EXTENSIONS = {
        '.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', 
        '.mpeg', '.mpg', '.m4v', '.ts', '.rmvb', '.webm', '.m2ts'
    }
    
    # 字幕文件扩展名
    SUBTITLE_EXTENSIONS = {
        '.srt', '.ass', '.ssa', '.sub', '.vtt'
    }
    
    # 图片文件扩展名
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'
    }
    
    # NFO 文件扩展名
    NFO_EXTENSIONS = {'.nfo'}
    
    def __init__(
        self,
        url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        public_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        subtitle_extensions: Optional[List[str]] = None,
        image_extensions: Optional[List[str]] = None,
        nfo_extensions: Optional[List[str]] = None
    ):
        """
        初始化 OpenList 客户端
        
        Args:
            url: OpenList 服务器地址
            username: 用户名
            password: 密码
            token: JWT Token
            public_url: 公共访问地址
            timeout: 请求超时时间
            max_retries: 最大重试次数
            subtitle_extensions: 自定义字幕扩展名列表
            image_extensions: 自定义图片扩展名列表
            nfo_extensions: 自定义 NFO 扩展名列表
        """
        self.url = url.rstrip('/')
        self.username = username
        self.password = password
        self._token = token
        self.public_url = public_url.rstrip('/') if public_url else None
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 使用自定义扩展名或默认值
        if subtitle_extensions:
            self.SUBTITLE_EXTENSIONS = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in subtitle_extensions}
        if image_extensions:
            self.IMAGE_EXTENSIONS = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in image_extensions}
        if nfo_extensions:
            self.NFO_EXTENSIONS = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in nfo_extensions}
            
        self._session = requests.Session()
        # 配置重试适配器
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            backoff_factor=1
        )
        # 配置连接池：最大 20 个连接，每个 host 最大 10 个
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=20
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
    
    @property
    def token(self) -> Optional[str]:
        """获取 Token，如果没有则尝试登录"""
        if not self._token:
            if self.username and self.password:
                self.login()
        return self._token
    
    def login(self) -> bool:
        """
        登录 OpenList 获取 Token
        
        Returns:
            是否登录成功
        """
        try:
            response = self._session.post(
                f"{self.url}/api/auth/login",
                json={
                    "username": self.username,
                    "password": self.password
                },
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    self._token = data.get('data', {}).get('token')
                    if self._token:
                        logging.info(f"✅ OpenList 登录成功: {self.url}")
                        return True
                    else:
                        logging.error("❌ OpenList 登录失败: 未返回 Token")
                        return False
                else:
                    logging.error(f"❌ OpenList 登录失败: {data.get('message', '未知错误')}")
                    return False
            else:
                logging.error(f"❌ OpenList 登录失败: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"❌ OpenList 登录异常: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json'
        }
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers
    
    def list_dir(
        self, 
        path: str, 
        page: int = 1, 
        per_page: int = 100,
        refresh: bool = False
    ) -> Dict[str, Any]:
        """
        列出目录内容
        
        Args:
            path: 目录路径
            page: 页码（从 1 开始）
            per_page: 每页数量
            refresh: 是否刷新缓存
            
        Returns:
            包含文件列表的字典，格式如：
            {
                'content': [...],
                'total': 100,
                'provider': 'xxx'
            }
        """
        try:
            response = self._session.post(
                f"{self.url}/api/fs/list",
                json={
                    "path": path,
                    "page": page,
                    "per_page": per_page,
                    "refresh": refresh
                },
                headers=self._get_headers(),
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    return data.get('data', {})
                else:
                    logging.warning(f"⚠️ 列目录失败: {path} - {data.get('message', '未知错误')}")
                    return {}
            else:
                logging.warning(f"⚠️ 列目录失败: {path} - HTTP {response.status_code}")
                return {}
                
        except Exception as e:
            logging.error(f"❌ 列目录异常: {path} - {e}")
            return {}
    
    def get_file_info(self, path: str) -> Optional[Dict[str, Any]]:
        """
        获取文件详细信息
        
        Args:
            path: 文件路径
            
        Returns:
            文件信息字典或 None
        """
        try:
            response = self._session.post(
                f"{self.url}/api/fs/get",
                json={"path": path},
                headers=self._get_headers(),
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    return data.get('data', {})
                else:
                    logging.warning(f"⚠️ 获取文件信息失败: {path} - {data.get('message')}")
                    return None
            else:
                logging.warning(f"⚠️ 获取文件信息失败: {path} - HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logging.error(f"❌ 获取文件信息异常: {path} - {e}")
            return None
    
    def iter_all_files(
        self,
        root_path: str,
        per_page: int = 100
    ) -> AsyncIterator[OpenListFile]:
        """
        递归遍历目录下的所有文件（同步生成器）
        
        Args:
            root_path: 根目录路径
            per_page: 每页数量
            
        Yields:
            OpenListFile 对象
        """
        def _iter_recursive(path: str):
            page = 1
            while True:
                result = self.list_dir(path, page=page, per_page=per_page)
                
                if not result or 'content' not in result:
                    break
                
                content = result['content']
                if not content:
                    break
                
                for item in content:
                    name = item.get('name', '')
                    is_dir = item.get('is_dir', False)
                    
                    # 构建完整路径
                    full_path = f"{path}/{name}".replace('//', '/')
                    
                    if is_dir:
                        # 递归处理子目录
                        yield from _iter_recursive(full_path)
                    else:
                        # 返回文件信息
                        file_obj = OpenListFile(
                            name=name,
                            path=path,
                            full_path=full_path,
                            is_dir=False,
                            size=item.get('size', 0),
                            modified=item.get('modified', ''),
                            sign=item.get('sign', ''),
                            raw_url=item.get('raw_url', '')
                        )
                        
                        # 构建下载链接
                        if file_obj.sign:
                            download_url = f"{self.url}/d/{file_obj.sign}/{file_obj.name}"
                            if self.public_url:
                                download_url = download_url.replace(self.url, self.public_url)
                            file_obj.download_url = download_url
                        
                        yield file_obj
                
                # 检查是否还有下一页
                total = result.get('total', 0)
                if page * per_page >= total:
                    break
                
                page += 1
        
        yield from _iter_recursive(root_path)
    
    def is_video_file(self, file: OpenListFile) -> bool:
        """判断是否为视频文件"""
        return file.suffix.lower() in self.VIDEO_EXTENSIONS
    
    def is_subtitle_file(self, file: OpenListFile) -> bool:
        """判断是否为字幕文件"""
        return file.suffix.lower() in self.SUBTITLE_EXTENSIONS
    
    def is_image_file(self, file: OpenListFile) -> bool:
        """判断是否为图片文件"""
        return file.suffix.lower() in self.IMAGE_EXTENSIONS
    
    def is_nfo_file(self, file: OpenListFile) -> bool:
        """判断是否为 NFO 文件"""
        return file.suffix.lower() in self.NFO_EXTENSIONS
    
    def test_connection(self) -> bool:
        """
        测试连接是否正常
        
        Returns:
            是否连接成功
        """
        try:
            # 尝试获取用户信息
            response = self._session.get(
                f"{self.url}/api/me",
                headers=self._get_headers(),
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    logging.info(f"✅ OpenList 连接测试成功: {self.url}")
                    return True
            
            # 如果失败且没有 token，尝试登录
            if not self._token and self.username and self.password:
                return self.login()
            
            return False
            
        except Exception as e:
            logging.error(f"❌ OpenList 连接测试失败: {e}")
            return False

    def remove_files(self, paths: List[str]) -> bool:
        """
        删除 OpenList 上的文件或目录
        
        Args:
            paths: 要删除的路径列表
            
        Returns:
            是否删除成功
        """
        if not paths:
            return True
            
        try:
            response = self._session.post(
                f"{self.url}/api/fs/remove",
                json={"paths": paths},
                headers=self._get_headers(),
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == 200:
                    logging.info(f"✅ OpenList 删除成功: {len(paths)} 个文件")
                    return True
                else:
                    logging.warning(f"⚠️ OpenList 删除失败: {data.get('message', '未知错误')}")
                    return False
            else:
                logging.warning(f"⚠️ OpenList 删除失败: HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"❌ OpenList 删除异常: {e}")
            return False
    
    def close(self):
        """关闭会话"""
        if self._session:
            self._session.close()
    
    def __enter__(self):
        """支持 with 语句"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """支持 with 语句"""
        self.close()
