"""
WebDAV 最小客户端
"""

import posixpath
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlsplit

import requests


class WebDavClient:
    """基于 requests 的 WebDAV 客户端"""

    def __init__(
        self,
        url: str,
        username: str = "",
        password: str = "",
        root_path: str = "/",
        timeout: int = 30,
    ):
        self.url = url.rstrip("/")
        self.root_path = self._normalize_path(root_path)
        self.timeout = timeout
        self.session = requests.Session()
        if username or password:
            self.session.auth = (username, password)

    def test_connection(self) -> bool:
        """测试根目录是否可访问"""
        return self.info("/") is not None

    def list_dir(self, path: str = "/") -> list[dict]:
        """列出一级子目录"""
        response = self._request(
            "PROPFIND",
            path,
            headers={"Depth": "1"},
            data=self._propfind_body(),
        )
        if response.status_code == 404:
            return []
        self._raise_for_status(response, {207})

        base_path = self._path_from_url(self._url(path)).rstrip("/")
        dirs = []
        for item in self._parse_multistatus(response.text):
            href_path = self._path_from_url(item["href"]).rstrip("/")
            if href_path == base_path or not item["is_dir"]:
                continue
            dirs.append({
                "name": unquote(posixpath.basename(href_path)),
                "path": self._relative_from_base(href_path),
            })
        return sorted(dirs, key=lambda item: item["name"].lower())

    def info(self, path: str) -> Optional[dict]:
        """获取文件或目录信息，不存在返回 None"""
        response = self._request(
            "PROPFIND",
            path,
            headers={"Depth": "0"},
            data=self._propfind_body(),
        )
        if response.status_code == 404:
            return None
        self._raise_for_status(response, {207})
        items = self._parse_multistatus(response.text)
        return items[0] if items else None

    def ensure_dir(self, path: str):
        """逐级创建远端目录"""
        normalized = self._normalize_path(path)
        if normalized == "/":
            return

        current = ""
        for part in normalized.strip("/").split("/"):
            current = f"{current}/{part}"
            response = self._request("MKCOL", current)
            if response.status_code not in {200, 201, 204, 405}:
                self._raise_for_status(response, {200, 201, 204, 405})

    def upload_file(self, local_file: Path, remote_path: str):
        """上传文件到临时名，成功后 MOVE 到正式名"""
        remote_path = self._normalize_path(remote_path)
        self.ensure_dir(posixpath.dirname(remote_path))
        part_path = f"{remote_path}.cloudgather.part"

        with open(local_file, "rb") as file_obj:
            put_response = self._request("PUT", part_path, data=file_obj)
        self._raise_for_status(put_response, set(range(200, 300)))

        move_response = self._request(
            "MOVE",
            part_path,
            headers={
                "Destination": self._url(remote_path),
                "Overwrite": "T",
            },
        )
        self._raise_for_status(move_response, {200, 201, 204})

        info = self.info(remote_path)
        if not info or info.get("size") != local_file.stat().st_size:
            raise IOError(f"WebDAV 上传校验失败: {remote_path}")

    def _request(self, method: str, path: str, **kwargs):
        return self.session.request(
            method,
            self._url(path),
            timeout=self.timeout,
            **kwargs,
        )

    def _url(self, path: str) -> str:
        remote_path = self._normalize_path(posixpath.join(self.root_path, path.lstrip("/")))
        if remote_path == "/":
            return self.url
        encoded = "/".join(quote(part) for part in remote_path.strip("/").split("/"))
        return f"{self.url}/{encoded}"

    def _relative_from_base(self, href_path: str) -> str:
        base_path = self._path_from_url(self.url).rstrip("/")
        rel_path = href_path[len(base_path):] if href_path.startswith(base_path) else href_path
        if self.root_path != "/" and rel_path.startswith(self.root_path):
            rel_path = rel_path[len(self.root_path):]
        return self._normalize_path(unquote(rel_path))

    @staticmethod
    def _path_from_url(url: str) -> str:
        return urlsplit(url).path or "/"

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = posixpath.normpath("/" + (path or "/").strip("/"))
        return "/" if normalized == "/." else normalized

    @staticmethod
    def _propfind_body() -> str:
        return """<?xml version="1.0" encoding="utf-8"?>
<propfind xmlns="DAV:">
  <prop>
    <resourcetype/>
    <getcontentlength/>
    <getlastmodified/>
  </prop>
</propfind>"""

    @staticmethod
    def _parse_multistatus(body: str) -> list[dict]:
        root = ET.fromstring(body)
        items = []
        for response in root.findall("{DAV:}response"):
            href = response.findtext("{DAV:}href", default="")
            prop = response.find("{DAV:}propstat/{DAV:}prop")
            if prop is None:
                continue
            resourcetype = prop.find("{DAV:}resourcetype")
            is_dir = resourcetype is not None and resourcetype.find("{DAV:}collection") is not None
            size_text = prop.findtext("{DAV:}getcontentlength")
            modified_text = prop.findtext("{DAV:}getlastmodified")
            items.append({
                "href": href,
                "is_dir": is_dir,
                "size": int(size_text) if size_text and size_text.isdigit() else None,
                "modified": WebDavClient._parse_modified(modified_text),
            })
        return items

    @staticmethod
    def _parse_modified(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).timestamp()
        except Exception:
            return None

    @staticmethod
    def _raise_for_status(response, expected: set[int]):
        if response.status_code not in expected:
            raise requests.HTTPError(
                f"WebDAV {response.request.method} {response.url} HTTP {response.status_code}: {response.text[:200]}",
                response=response,
            )
