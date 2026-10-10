from pathlib import Path

from .model import EnvironmentStatus, PyEnv
from .scan import ScanResult
from .schema import Environment, Scan


class ScanResultConverter:
    """将扫描结果转换为数据库 schema；由 CLI 显式调用，不负责写库。"""

    @classmethod
    def convert(cls, result: ScanResult) -> tuple[Scan, list[Environment]]:
        environments = [
            cls._convert_environment(env, result.finished_at, result.scan_id)
            for env in result.environments
        ]
        scan = Scan(
            id=result.scan_id,
            root=result.root,
            started_at=result.started_at,
            finished_at=result.finished_at,
            status=result.status,
            environments_found=len(environments),
        )
        return scan, environments

    @staticmethod
    def _convert_environment(env: PyEnv, seen_at: int, scan_id: int) -> Environment:
        if env.cfg_path is None:
            raise ValueError("PyEnv 缺少 cfg_path，无法确定环境目录")

        path = env.cfg_path.parent
        # 保留环境内的解释器路径，避免 resolve() 跟随符号链接到基础 Python。
        python_executable = next(
            (
                candidate
                for candidate in (path / "bin/python", path / "Scripts/python.exe")
                if candidate.is_file()
            ),
            None,
        )
        home = getattr(env, "home", None)
        manager = getattr(env, "manager", None)
        if manager is None:
            if hasattr(env, "uv"):
                manager = "uv"
            elif hasattr(env, "virtualenv"):
                manager = "virtualenv"
            else:
                manager = "venv"

        return Environment(
            id=None,  # 数据库分配 ID。
            path=path,
            python_executable=python_executable,
            python_version=getattr(env, "version", None),
            python_home=Path(home).expanduser() if home else None,
            manager=manager,
            status=EnvironmentStatus.LIVE,
            discovered_at=seen_at,
            last_seen_at=seen_at,
            last_verified_at=None,
            first_seen_scan_id=scan_id,
            last_seen_scan_id=scan_id,
            size_bytes=None,
            size_updated_at=None,
        )
