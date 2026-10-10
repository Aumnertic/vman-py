from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from time import time
from typing import TYPE_CHECKING

from .log import close_logger, create_scan_logger
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
        self._logger: logging.Logger | None = None

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = create_scan_logger(self.manifest.path.parent)
        return self._logger

    def close(self) -> None:
        if self._logger is not None:
            close_logger(self._logger)
            self._logger = None

    # 多线程并发扫描
    async def scan(self, root: str = "~", max_workers: int = 4) -> ScanResult:
        try:
            scan_id = self.manifest.next_scan_id()
        except Exception:
            self.logger.exception("无法分配扫描编号 root=%s", root)
            raise
        started_at = int(time())
        root_path = Path(root)
        all_cfgs: list[Path] = []
        status = ScanStatus.SUCCESS
        self.logger.info("扫描开始 scan_id=%s root=%s", scan_id, root_path)
        try:
            root_path = root_path.expanduser().resolve()
            queue = [root_path]
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                while queue:
                    futures = [
                        (
                            path,
                            executor.submit(self._scan_folder, path, path == root_path),
                        )
                        for path in queue
                    ]
                    queue = []
                    for path, future in futures:
                        # 在线程任务边界隔离异常，由 _scan_error 记录并判定状态。
                        try:
                            venv_path, to_be_scan, folder_status = future.result()
                        except Exception as exc:  # noqa: BLE001
                            folder_status = self._scan_error(
                                path, exc, path == root_path
                            )
                            venv_path, to_be_scan = None, []
                        if folder_status is ScanStatus.FAILED:
                            status = ScanStatus.FAILED
                        if venv_path:
                            all_cfgs.append(venv_path)
                        queue.extend(to_be_scan)
        except Exception as exc:  # noqa: BLE001
            if self._scan_error(root_path, exc, is_root=True) is ScanStatus.FAILED:
                status = ScanStatus.FAILED

        environments, parse_status = await self._cfg_handle(all_cfgs)
        if parse_status is ScanStatus.FAILED:
            status = ScanStatus.FAILED
        self.logger.info(
            "扫描结束 scan_id=%s root=%s status=%s envs_found=%s",
            scan_id,
            root_path,
            status.name,
            len(environments),
        )
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
        self.logger.info("检查开始 envs_count=%s", len(environments))
        verified_at = int(time())
        results = await asyncio.gather(
            *(
                asyncio.to_thread(self._check_one, env, verified_at)
                for env in environments
            )
        )
        checked = [env for env in results if env is not None]
        Inventory.update_env_statuses(conn, checked)
        self.logger.info(
            "检查结束 checked=%s missing=%s skipped=%s",
            len(checked),
            sum(env.status is EnvironmentStatus.MISS for env in checked),
            len(environments) - len(checked),
        )
        return checked

    def _check_one(self, env: Environment, verified_at: int) -> Environment | None:
        cfg = env.path / "pyvenv.cfg"
        try:
            exists = stat.S_ISREG(cfg.stat().st_mode)
        except FileNotFoundError, NotADirectoryError:
            exists = False
        except OSError as exc:
            self.logger.warning("跳过检查 %s: %s", env.path, exc)
            return None

        return replace(
            env,
            status=EnvironmentStatus.LIVE if exists else EnvironmentStatus.MISS,
            last_verified_at=verified_at,
        )

    async def _cfg_handle(self, all_cfgs: list[Path]) -> tuple[list[PyEnv], ScanStatus]:
        tasks = [self._parse_one(cfg) for cfg in all_cfgs]
        results = await asyncio.gather(*tasks)
        environments = [env for env, _ in results if env is not None]
        status = (
            ScanStatus.FAILED
            if any(status is ScanStatus.FAILED for _, status in results)
            else ScanStatus.SUCCESS
        )
        return environments, status

    async def _parse_one(self, cfg: Path) -> tuple[PyEnv | None, ScanStatus]:
        try:
            lines = await asyncio.to_thread(self._read_file_lines, cfg)
            env = PyEnv()
            for line in lines:
                k, v = line.strip().split("=", 1)
                setattr(env, k.strip(), v.strip())
            env.cfg_path = cfg
        except (PermissionError, FileNotFoundError, NotADirectoryError) as exc:
            self.logger.warning("跳过配置 %s: %s", cfg, exc)
            return None, ScanStatus.SUCCESS
        except Exception:
            self.logger.exception("配置解析失败 %s", cfg)
            return None, ScanStatus.FAILED
        self.logger.info("解析环境 %s", cfg.parent)
        return env, ScanStatus.SUCCESS

    def _read_file_lines(self, cfg: Path) -> list[str]:
        with open(cfg, "r", encoding="utf-8") as f:
            return f.readlines()

    # 单层目录扫描
    def _scan_folder(
        self, path: Path, is_root: bool = False
    ) -> tuple[Path | None, list[Path], ScanStatus]:
        entries_list = []
        status = ScanStatus.SUCCESS
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        # 拿到cfg文件的目录
                        if entry.is_file() and entry.name == "pyvenv.cfg":
                            return Path(entry.path), [], status
                        if entry.is_dir() and entry.name not in self.IGNORE_LIST:
                            entries_list.append(Path(entry.path))
                    except Exception as exc:  # noqa: BLE001
                        if self._scan_error(Path(entry.path), exc) is ScanStatus.FAILED:
                            status = ScanStatus.FAILED
        except Exception as exc:  # noqa: BLE001
            if self._scan_error(path, exc, is_root) is ScanStatus.FAILED:
                status = ScanStatus.FAILED
        return None, entries_list, status

    def _scan_error(
        self, path: Path, exc: Exception, is_root: bool = False
    ) -> ScanStatus:
        if isinstance(exc, PermissionError) or (
            not is_root and isinstance(exc, (FileNotFoundError, NotADirectoryError))
        ):
            self.logger.warning("跳过目录 %s: %s", path, exc)
            return ScanStatus.SUCCESS
        self.logger.error(
            "扫描失败 %s: %s", path, exc, exc_info=(type(exc), exc, exc.__traceback__)
        )
        return ScanStatus.FAILED


if __name__ == "__main__":
    import asyncio

    async def main():
        scanner = PyEnvScanner()
        try:
            result = await scanner.scan(".")
            print("结果:", result)
        finally:
            scanner.close()

    asyncio.run(main())
