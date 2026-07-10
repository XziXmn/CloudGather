import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask

import api.settings as settings_api
from api.tasks import init_tasks_bp, tasks_bp


class FakeWebDavClient:
    def test_connection(self):
        return True

    def list_dir(self, path):
        return [{"name": "Movies", "path": "/Movies"}]


class FakeScheduler:
    def __init__(self):
        self.tasks = []
        self.task_progress = {}
        self.task_stats = {}

    def add_task(self, task):
        self.tasks.append(task)
        return True

    def get_all_tasks(self):
        return self.tasks

    def get_next_run_time(self, task_id):
        return None


def create_app(temp_dir: Path):
    settings_api.WEBDAV_CONFIG_PATH = temp_dir / "webdav.json"
    settings_api.OPENLIST_CONFIG_PATH = temp_dir / "openlist.json"
    settings_api.EXTENSIONS_CONFIG_PATH = temp_dir / "extensions.json"
    settings_api.SYSTEM_CONFIG_PATH = temp_dir / "system.json"
    settings_api.create_webdav_client = lambda config: FakeWebDavClient()

    app = Flask(__name__)
    settings_api.init_settings_bp(False)
    app.register_blueprint(settings_api.settings_bp, url_prefix="/api")

    scheduler = FakeScheduler()
    init_tasks_bp(scheduler, lambda message: None, False, {}, None)
    app.register_blueprint(tasks_bp, url_prefix="/api")
    return app, scheduler


def main():
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        app, scheduler = create_app(temp_dir)
        client = app.test_client()

        response = client.post("/api/settings/webdav", json={
            "url": "https://example.test/dav",
            "username": "u",
            "password": "secret",
            "root_path": "/root",
            "timeout": 30,
        })
        assert response.status_code == 200
        assert response.get_json()["success"] is True

        response = client.get("/api/settings/webdav")
        data = response.get_json()
        assert data["config"]["password"] == ""
        assert data["config"]["root_path"] == "/root"

        response = client.post("/api/settings/webdav/test", json={
            "url": "https://example.test/dav",
            "username": "u",
            "password": "",
            "root_path": "/root",
        })
        assert response.get_json()["success"] is True

        response = client.get("/api/webdav/directories?path=/")
        data = response.get_json()
        assert data["success"] is True
        assert data["directories"] == [{"name": "Movies", "path": "/Movies"}]

        source_dir = temp_dir / "source"
        source_dir.mkdir()
        response = client.post("/api/tasks", json={
            "name": "webdav",
            "source_path": str(source_dir),
            "target_path": "/Movies",
            "target_type": "WEBDAV",
            "schedule_type": "CRON",
            "cron_expression": "0 2 * * *",
            "rule_not_exists": True,
            "copy_mode": "COPY",
        })
        assert response.status_code == 200, response.get_json()
        assert scheduler.tasks[0].target_type == "WEBDAV"

        response = client.post("/api/tasks", json={
            "name": "bad",
            "source_path": str(source_dir),
            "target_path": "/Movies",
            "target_type": "WEBDAV",
            "schedule_type": "CRON",
            "cron_expression": "0 2 * * *",
            "copy_mode": "HARDLINK",
        })
        assert response.status_code == 400
        assert "WebDAV" in response.get_json()["error"]


if __name__ == "__main__":
    main()
