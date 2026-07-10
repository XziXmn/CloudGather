import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.worker import FileSyncer


def run_case(copy_mode: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_dir = root / "source"
        target_dir = root / "target"
        source_dir.mkdir()
        source_file = source_dir / "movie.mkv"
        source_file.write_text("media", encoding="utf-8")

        syncer = FileSyncer(str(source_dir), str(target_dir))
        syncer.STABILITY_CHECK_DELAY = 0
        stats = syncer.sync_directory(rule_not_exists=True, copy_mode=copy_mode)

        target_file = target_dir / "movie.mkv"
        assert stats["success"] == 1, stats
        assert target_file.exists()
        assert target_file.read_text(encoding="utf-8") == "media"
        if copy_mode == "HARDLINK":
            assert os.path.samefile(source_file, target_file)
        if copy_mode == "SYMLINK":
            assert target_file.is_symlink()
            assert target_file.resolve() == source_file.resolve()


def main():
    run_case("COPY")

    run_case("HARDLINK")

    with tempfile.TemporaryDirectory() as temp_dir:
        probe = Path(temp_dir) / "probe"
        try:
            os.symlink(__file__, probe)
        except OSError as exc:
            print(f"SYMLINK skipped: {exc}")
            return

    run_case("SYMLINK")


if __name__ == "__main__":
    main()
