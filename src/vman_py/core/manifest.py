import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .config import DEFAULT_MANIFEST_PATH


class Manifest:
    """在 manifest.json 中保存最后分配的扫描编号。"""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(
            path if path is not None else DEFAULT_MANIFEST_PATH
        ).expanduser()

    def next_scan_id(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 锁文件独立于 manifest，原子替换 JSON 文件后仍能持有同一把锁。
        with self._lock():
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    data = json.load(stream)
            except FileNotFoundError:
                data = {}
            except (ValueError, UnicodeError) as exc:
                raise ValueError(f"无法读取 manifest {self.path}: {exc}") from exc

            if not isinstance(data, dict):
                raise TypeError(f"manifest {self.path} 必须是 JSON 对象")
            last_scan_id = data.get("last_scan_id", 0)
            if type(last_scan_id) is not int or last_scan_id < 0:
                raise ValueError(f"manifest {self.path} 的 last_scan_id 必须是非负整数")

            scan_id = last_scan_id + 1
            data["last_scan_id"] = scan_id
            self._write(data)
            return scan_id

    @contextmanager
    def _lock(self):
        with self.path.with_suffix(self.path.suffix + ".lock").open("a+b") as lock:
            if os.name == "nt":
                import msvcrt

                if lock.tell() == 0:
                    lock.write(b"\0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write(self, data: dict) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
