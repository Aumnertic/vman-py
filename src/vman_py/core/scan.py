from typing import Any
import os
from pathlib import Path
from .model import PyEnv
from concurrent.futures import ThreadPoolExecutor
import asyncio

# 返回PyEnv对象列表，以及一些必要的信息
type ScanResult = tuple[list[PyEnv] | None, Any]

# 扫描状态
type ScanStatus = Any

# TODO: 完善默认忽略的目录列表
DEFAULT_IGNORE_LIST = {"node_moudules", "targets"}

class PyEnvScanner:
    def __init__(self):
        self.IGNORE_LIST: set = DEFAULT_IGNORE_LIST

    # 多线程并发扫描
    async def scan(self, root: str = "~", max_workers: int = 4) -> ScanResult:
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

        return await self._cfg_handle(all_cfgs)

    async def _cfg_handle(self, all_cfgs: list[Path]) -> ScanResult:
        tasks = [self._parse_one(cfg) for cfg in all_cfgs]
        envs = await asyncio.gather(*tasks, return_exceptions=True)
        env = []
        error = []
        for cfg, err in zip(envs, all_cfgs):
            if isinstance(cfg, Exception):
                error.append((cfg, str(err)))
            else:
                env.append(cfg)
        return env, error

    async def _parse_one(self, cfg: Path) -> PyEnv:
        lines = await asyncio.to_thread(self._read_file_lines, cfg)
        env = PyEnv()
        for line in lines:
            k, v = line.strip().split("=", 1)
            setattr(env, k.strip(), v.strip())

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
