import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.webdav_client import WebDavClient
from core.worker import WebDavSyncer


class MiniWebDavHandler(BaseHTTPRequestHandler):
    root_dir: Path = Path()

    def log_message(self, format, *args):
        return

    def do_PROPFIND(self):
        path = self._local_path()
        if not path.exists():
            self.send_error(404)
            return

        depth = self.headers.get("Depth", "0")
        items = [path]
        if depth == "1" and path.is_dir():
            items.extend(sorted(path.iterdir(), key=lambda item: item.name.lower()))

        body = self._multistatus(items).encode("utf-8")
        self.send_response(207)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_MKCOL(self):
        path = self._local_path()
        if path.exists():
            self.send_response(405)
            self.end_headers()
            return
        path.mkdir(parents=True, exist_ok=True)
        self.send_response(201)
        self.end_headers()

    def do_PUT(self):
        path = self._local_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        length = int(self.headers.get("Content-Length", "0"))
        path.write_bytes(self.rfile.read(length))
        self.send_response(201)
        self.end_headers()

    def do_MOVE(self):
        source = self._local_path()
        destination_header = self.headers.get("Destination")
        if not destination_header:
            self.send_error(400)
            return
        destination = self._local_path(destination_header)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            destination.unlink()
        shutil.move(str(source), str(destination))
        self.send_response(201)
        self.end_headers()

    def _local_path(self, raw_url: str | None = None) -> Path:
        parsed_path = urlsplit(raw_url or self.path).path
        rel_path = unquote(parsed_path).lstrip("/")
        return (self.root_dir / rel_path).resolve()

    def _multistatus(self, items: list[Path]) -> str:
        responses = []
        for item in items:
            href = "/" + item.relative_to(self.root_dir).as_posix()
            if item.is_dir() and not href.endswith("/"):
                href += "/"
            collection = "<d:collection/>" if item.is_dir() else ""
            size = "" if item.is_dir() else f"<d:getcontentlength>{item.stat().st_size}</d:getcontentlength>"
            responses.append(f"""
<d:response>
  <d:href>{href}</d:href>
  <d:propstat>
    <d:prop>
      <d:resourcetype>{collection}</d:resourcetype>
      {size}
      <d:getlastmodified>Fri, 01 Jan 2021 00:00:00 GMT</d:getlastmodified>
    </d:prop>
  </d:propstat>
</d:response>""")
        return f"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">{''.join(responses)}
</d:multistatus>"""


def main():
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        dav_root = temp_dir / "dav"
        source_dir = temp_dir / "source"
        dav_root.mkdir()
        source_dir.mkdir()
        (source_dir / "movie.mkv").write_text("media", encoding="utf-8")
        (source_dir / "poster.jpg").write_text("poster", encoding="utf-8")

        MiniWebDavHandler.root_dir = dav_root
        server = ThreadingHTTPServer(("127.0.0.1", 0), MiniWebDavHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            url = f"http://127.0.0.1:{server.server_port}"
            client = WebDavClient(url, root_path="/")
            syncer = WebDavSyncer(str(source_dir), "/Movies", client)
            syncer.STABILITY_CHECK_DELAY = 0

            stats = syncer.sync_directory(
                rule_not_exists=True,
                suffix_mode="INCLUDE",
                suffix_list=["mkv"],
                retry_count=1,
            )

            assert stats["total"] == 2, stats
            assert stats["success"] == 1, stats
            assert stats["skipped_filtered"] == 1, stats
            assert (dav_root / "Movies" / "movie.mkv").read_text(encoding="utf-8") == "media"
            assert not (dav_root / "Movies" / "movie.mkv.cloudgather.part").exists()
            assert not (dav_root / "Movies" / "poster.jpg").exists()

            second_stats = syncer.sync_directory(rule_not_exists=True, retry_count=0)
            assert second_stats["skipped_unchanged"] >= 1, second_stats
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
