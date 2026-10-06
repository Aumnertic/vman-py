import queue
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# 忽略列表
IGNORE_LIST = {}

# Python环境对象
class PyEnv:
    # 从cfg中解析并读取数据，预计写成lazy的
    def __init__(cfg):
        pass

# 单层目录扫描
def scan_folder(path: Path) -> tuple[Path | None, list[Path]]:
    with os.scandir(path) as entries:
        entries_list = []

        for entry in entries:
            # 拿到cfg文件的目录
            if entry.is_file() and entry.name == "pyvenv.cfg":
                return Path(entry.path), []
            if entry.is_dir() and entry.name not in IGNORE_LIST:
                # 待扫描目录
                entries_list.append(Path(entry.path))

        return None, entries_list


# 多线程并发扫描
def scan(root: str = "～", max_workers: int | None = None):
    root_path = Path(root).expanduser().resolve()
    all_cfgs = []

    queue = [root_path]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while queue:
            results = executor.map(scan_folder, queue)

            # 单层扫描，所以这里需要清空一下
            queue.clear()

            for venv_path, to_be_scan in results:
                if venv_path:
                    all_cfgs.append(venv_path)
                if to_be_scan:
                    queue.extend(to_be_scan)

        return all_cfgs

def main():
    pass

if __name__ == "__main__":
    main()
