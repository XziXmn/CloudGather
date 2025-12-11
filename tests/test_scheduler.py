import tempfile
import unittest
from pathlib import Path

from core.models import SyncTask, TaskStatus
from core.scheduler import TaskScheduler


class TaskSchedulerTests(unittest.TestCase):
    def test_add_and_reload_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "tasks.json"
            scheduler = TaskScheduler(config_path=str(config_path))
            logs: list[str] = []
            scheduler.set_log_callback(logs.append)

            task = SyncTask(
                name="demo",
                source_path="/tmp/source",
                target_path="/tmp/target",
                interval=30,
            )

            self.assertTrue(scheduler.add_task(task))
            self.assertTrue(config_path.exists())
            self.assertIn("✓ 任务已添加", "\n".join(logs))

            reloaded = TaskScheduler(config_path=str(config_path))
            loaded_task = reloaded.get_task(task.id)

            self.assertIsNotNone(loaded_task)
            self.assertEqual(loaded_task.name, task.name)
            self.assertEqual(loaded_task.status, TaskStatus.IDLE)

    def test_sync_task_serialization(self):
        task = SyncTask(
            name="serialize",
            source_path="/data/src",
            target_path="/data/dst",
            interval=120,
            verify_md5=True,
            recursive=False,
            enabled=False,
        )

        serialized = task.to_dict()
        self.assertEqual(serialized["name"], "serialize")
        self.assertEqual(serialized["interval"], 120)
        self.assertTrue(serialized["verify_md5"])
        self.assertFalse(serialized["enabled"])

        restored = SyncTask.from_dict(serialized)
        self.assertEqual(restored.name, task.name)
        self.assertEqual(restored.source_path, task.source_path)
        self.assertEqual(restored.target_path, task.target_path)
        self.assertEqual(restored.interval, task.interval)
        self.assertEqual(restored.status, TaskStatus.IDLE)
        self.assertFalse(restored.enabled)
        self.assertTrue(restored.verify_md5)
        self.assertFalse(restored.recursive)


if __name__ == "__main__":
    unittest.main()
