from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from time import time
from typing import TYPE_CHECKING

from .manifest import Manifest
from .model import EnvironmentStatus, PyEnv

if TYPE_CHECKING:
    from .schema import Environment

# 扫描状态
ScanStatus = Enum("ScanStatus", ["SUCCESS", "FAILED"])


@dataclass
class ScanResult:
    scan_id: int
    environments: list[PyEnv]
    root: Path
    started_at: int
    finished_at: int
    status: ScanStatus


# TODO: 完善默认忽略的目录列表
DEFAULT_IGNORE_LIST = {"node_moudules", "targets"}


class PyEnvScanner:
    def __init__(self, manifest_path: str | Path | None = None):
        self.IGNORE_LIST: set = DEFAULT_IGNORE_LIST
        self.manifest = Manifest(manifest_path)

    # 多线程并发扫描
    async def scan(self, root: str = "~", max_workers: int = 4) -> ScanResult:
        scan_id = self.manifest.next_scan_id()
        started_at = int(time())
        root_path = Path(root).expanduser().resolve()
        all_cfgs = []

        queue = [root_path]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while queue:
                results = executor.map(self._scan_folder, queue)

                # 单层扫描，所以这里需要清空一下
                queue.clear()

                for venv_path, to_be_scan in results:
                    if venv_path:
                        all_cfgs.append(venv_path)
                    if to_be_scan:
                        queue.extend(to_be_scan)

        environments, status = await self._cfg_handle(all_cfgs)
        return ScanResult(
            scan_id=scan_id,
            environments=environments,
            root=root_path,
            started_at=started_at,
            finished_at=int(time()),
            status=status,
        )

    async def check(self, conn: sqlite3.Connection) -> list[Environment]:
        """检查库中环境的配置文件，保存状态和检查时间，返回已检查的环境。"""
        from .inventory import Inventory

        environments = Inventory.list_envs(conn)
        verified_at = int(time())
        results = await asyncio.gather(
            *(
                asyncio.to_thread(self._check_one, env, verified_at)
                for env in environments
            )
        )
        checked = [env for env in results if env is not None]
        Inventory.update_env_statuses(conn, checked)
        return checked

    def _check_one(self, env: Environment, verified_at: int) -> Environment | None:
        cfg = env.path / "pyvenv.cfg"
        try:
            exists = stat.S_ISREG(cfg.stat().st_mode)
        except FileNotFoundError, NotADirectoryError:
            exists = False
        except OSError as exc:
            print(f"跳过检查 {env.path}: {exc}")
            return None

        return replace(
            env,
            status=EnvironmentStatus.LIVE if exists else EnvironmentStatus.MISS,
            last_verified_at=verified_at,
        )

    async def _cfg_handle(self, all_cfgs: list[Path]) -> tuple[list[PyEnv], ScanStatus]:
        tasks = [self._parse_one(cfg) for cfg in all_cfgs]
        results = await asyncio.gather(*tasks)
        environments = [env for env in results if env is not None]
        status = (
            ScanStatus.SUCCESS
            if len(environments) == len(all_cfgs)
            else ScanStatus.FAILED
        )
        return environments, status

    async def _parse_one(self, cfg: Path) -> PyEnv | None:
        try:
            lines = await asyncio.to_thread(self._read_file_lines, cfg)
            env = PyEnv()
            for line in lines:
                k, v = line.strip().split("=", 1)
                setattr(env, k.strip(), v.strip())
            env.cfg_path = cfg
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"跳过配置 {cfg}: {exc}")
            return None
        return env

    def _read_file_lines(self, cfg: Path) -> list[str]:
        with open(cfg, "r", encoding="utf-8") as f:
            return f.readlines()

    # 单层目录扫描
    def _scan_folder(self, path: Path) -> tuple[Path | None, list[Path]]:
        with os.scandir(path) as entries:
            entries_list = []

            for entry in entries:
                # 拿到cfg文件的目录
                if entry.is_file() and entry.name == "pyvenv.cfg":
                    return Path(entry.path), []
                if entry.is_dir() and entry.name not in self.IGNORE_LIST:
                    # 待扫描目录
                    entries_list.append(Path(entry.path))

            return None, entries_list


if __name__ == "__main__":
    import asyncio

    async def main():
        scanner = PyEnvScanner()
        result = await scanner.scan(".")
        print("结果:", result)

    asyncio.run(main())
