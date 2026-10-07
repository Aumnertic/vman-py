from typing import Any
import os
from pathlib import Path
from .model import PyEnv
from concurrent.futures import ThreadPoolExecutor

# 返回PyEnv对象列表，以及一些必要的信息
type ScanResult = tuple[list[PyEnv] | None, Any]

# TODO: 完善默认忽略的目录列表
DEFAULT_IGNORE_LIST = {"node_moudules", "targets"}

class PyEnvScanner:
    def __init__(self):
        self.IGNORE_LIST: set = DEFAULT_IGNORE_LIST

    # 多线程并发扫描
    def scan(self, root: str = "~", max_workers: int = 4) -> ScanResult:
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

        return self._cfg_handle(all_cfgs)

    def _cfg_handle(self, all_cfgs: list[Path]) -> ScanResult:
        # 先写一个最简单的单线程阻塞函数来验证效果，之后改写为异步并发版本
        envs = []
        for cfg in all_cfgs:
            env = PyEnv()
            with open(cfg, "r") as f:
                for line in f.readlines():
                    line = line.strip().split("=")
                    k = line[0]
                    v = line[1]
                    setattr(env, k, v)

            envs.append(env)

        return envs, None

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
