import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.webdav_client import WebDavClient


def multistatus(items: list[dict]) -> str:
    responses = []
    for item in items:
        collection = "<d:collection/>" if item.get("is_dir") else ""
        size = "" if item.get("size") is None else f"<d:getcontentlength>{item['size']}</d:getcontentlength>"
        responses.append(f"""
<d:response>
  <d:href>{item['href']}</d:href>
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


class FakeRequest:
    def __init__(self, method):
        self.method = method


class FakeResponse:
    def __init__(self, method, url, status_code=207, text=""):
        self.request = FakeRequest(method)
        self.url = url
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self):
        self.calls = []
        self.auth = None

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("headers", {})))
        if method == "PROPFIND" and url.endswith("/root/Movies"):
            return FakeResponse(method, url, text=multistatus([
                {"href": "/dav/root/Movies/", "is_dir": True, "size": None},
                {"href": "/dav/root/Movies/Sub/", "is_dir": True, "size": None},
            ]))
        if method == "PROPFIND" and url.endswith("/root/Movies/a.mkv"):
            return FakeResponse(method, url, text=multistatus([
                {"href": "/dav/root/Movies/a.mkv", "is_dir": False, "size": 5},
            ]))
        if method == "MKCOL":
            return FakeResponse(method, url, status_code=201)
        if method == "PUT":
            return FakeResponse(method, url, status_code=201)
        if method == "MOVE":
            assert kwargs["headers"]["Destination"].endswith("/root/Movies/a.mkv")
            return FakeResponse(method, url, status_code=201)
        raise AssertionError((method, url))


def main():
    client = WebDavClient("https://example.test/dav", root_path="/root")
    fake_session = FakeSession()
    client.session = fake_session

    dirs = client.list_dir("/Movies")
    assert dirs == [{"name": "Sub", "path": "/Movies/Sub"}]

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = Path(temp_dir) / "a.mkv"
        file_path.write_text("media", encoding="utf-8")
        client.upload_file(file_path, "/Movies/a.mkv")

    methods = [call[0] for call in fake_session.calls]
    assert methods == ["PROPFIND", "MKCOL", "PUT", "MOVE", "PROPFIND"], methods


if __name__ == "__main__":
    main()
