import os
import tempfile
from pathlib import Path


def _usable(directory: Path) -> bool:
    """目录可创建且可写；用临时文件探测，兼容 Windows 权限。"""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory):
            pass
    except OSError:
        return False
    return True


class Config:
    """解析状态存储位置；默认目录不可用时退回当前目录。"""

    def __init__(self, state_dir: str | Path | None = None):
        if state_dir is None:
            state_dir = (
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
                / "vman-py"
            )
        self.state_dir = Path(state_dir)

    def manifest_path(self) -> Path:
        if _usable(self.state_dir):
            return self.state_dir / "manifest.json"
        fallback = Path.cwd()
        if _usable(fallback):
            return fallback / "manifest.json"
        raise OSError("状态目录与当前目录都不可写")
