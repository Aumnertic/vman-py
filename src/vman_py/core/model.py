from enum import Enum
from pathlib import Path

# 环境对象状态
EnvironmentStatus = Enum("EnvironmentStatus", ["MISS", "LIVE"])


# Python环境对象
class PyEnv:
    def __init__(self, cfg_path: Path | None = None):
        self.cfg_path = cfg_path

    def __repr__(self):
        return str(self.__dict__)
