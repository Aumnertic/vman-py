"""vman 命令入口：解析参数、调用业务层并输出结果。"""

import argparse
import asyncio
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vman_py.core.config import DEFAULT_MANIFEST_PATH
from vman_py.core.model import EnvironmentStatus
from vman_py.core.scan import ScanStatus
from vman_py.core.schema import Environment
from vman_py.core.service import VmanService

from .argly import add_arguments


class StorageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: Path = Field(
        default=DEFAULT_MANIFEST_PATH,
        json_schema_extra={
            "flags": ["-m", "--manifest"],
            "metavar": "MANIFEST_PATH",
            "help": f"manifest 文件路径（默认：{DEFAULT_MANIFEST_PATH}）",
        },
    )


class ScanArgs(StorageArgs):
    path: Path = Field(
        default=Path("~"),
        json_schema_extra={
            "positional": True,
            "metavar": "PATH",
            "help": "扫描根目录（默认：~）",
        },
    )


class ListArgs(StorageArgs):
    fresh: bool = Field(
        default=False,
        json_schema_extra={"help": "先检查已记录环境的存在状态，再显示列表"},
    )


COMMAND_MODELS: dict[str, type[StorageArgs]] = {
    "scan": ScanArgs,
    "list": ListArgs,
    "check": StorageArgs,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vman", description="扫描并管理 Python 环境")
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "scan": "先检查库存，再扫描目录并保存发现的环境",
        "list": "显示库存中的环境",
        "check": "检查库存中的环境并更新 LIVE/MISS 状态",
    }
    for name, model in COMMAND_MODELS.items():
        command = commands.add_parser(
            name, help=descriptions[name], description=descriptions[name]
        )
        add_arguments(command, model)
    return parser


def _print_envs(environments: list[Environment]) -> None:
    if not environments:
        print("暂无环境，运行 vman scan 扫描目录。")
        return
    rows = [["ID", "STATUS", "VERSION", "MANAGER", "PATH"]]
    rows.extend(
        [
            str(env.id),
            env.status.name,
            env.python_version or "-",
            env.manager or "-",
            str(env.path),
        ]
        for env in environments
    )
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


async def _run(command: str, options: StorageArgs) -> int:
    with VmanService(options.manifest) as service:
        if command == "scan" and isinstance(options, ScanArgs):
            result = await service.scan(options.path)
            detail = (
                "完成"
                if result.status is ScanStatus.SUCCESS
                else "FAILED（详见扫描日志）"
            )
            print(
                f"扫描 #{result.scan_id} {detail}，发现 {len(result.environments)} 个环境。"
            )
            return 0 if result.status is ScanStatus.SUCCESS else 1
        if command == "list" and isinstance(options, ListArgs):
            _print_envs(await service.list_envs(fresh=options.fresh))
        else:
            checked = await service.check()
            missing = sum(env.status is EnvironmentStatus.MISS for env in checked)
            print(f"已检查 {len(checked)} 个环境，其中 {missing} 个 MISS。")
            _print_envs(checked)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = vars(parser.parse_args(argv))
    command = arguments.pop("command")
    try:
        options = COMMAND_MODELS[command].model_validate(arguments)
    except ValidationError as exc:
        parser.error(str(exc))

    try:
        return asyncio.run(_run(command, options))
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f"vman: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
