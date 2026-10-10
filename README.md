# vman-py

扫描、记录和检查 Python 虚拟环境的命令行工具。通过 `pyvenv.cfg` 识别环境，
将环境库存和扫描记录保存在 SQLite 中，并用 `manifest.json` 持久化扫描编号。

## 安装与运行

需要 Python **3.14 或更新版本**以及 uv。在仓库目录中运行：

```sh
uv sync --locked
uv run vman --help
```

`vman`、`vman-py`、`python -m vman_py` 和根目录的 `main.py` 使用同一 CLI 入口：

```sh
uv run vman list
uv run vman-py list
uv run python -m vman_py list
uv run python main.py list
```

## 命令

```sh
uv run vman scan                     # 默认扫描 ~，先检查已有环境
uv run vman scan ./projects          # 扫描指定目录
uv run vman list                     # 显示数据库中已有的环境
uv run vman list --fresh             # 先检查存在状态，再显示完整列表
uv run vman check                    # 检查已有环境并保存 LIVE/MISS 状态
```

| 命令 | 行为 |
| --- | --- |
| `scan [PATH]` | 先检查全部已有环境，再扫描指定目录，将扫描记录和发现的环境入库 |
| `list` | 显示数据库中已有的环境，包括 `LIVE` 和 `MISS`，不检查文件系统 |
| `list --fresh` | 先检查已有环境的存在状态，再显示完整库存 |
| `check` | 检查已有环境，保存状态和检查时间，并显示本次检查结果 |

扫描路径 `PATH` 可省略，默认值为 `~`。manifest 参数也可省略，使用默认存储位置。
三个子命令均支持 `-m MANIFEST_PATH` 或 `--manifest MANIFEST_PATH`；
提供该选项时必须同时提供文件路径：

```sh
uv run vman scan ./projects -m ./state/manifest.json
uv run vman list --manifest ./state/manifest.json
uv run vman list --fresh -m ./state/manifest.json
uv run vman check -m ./state/manifest.json
```

列表展示环境的 ID、状态、Python 版本、管理器和路径。环境 ID 由 SQLite 自增分配；
重复扫描同一路径时更新已有记录，保留 ID 和首次发现信息。

## 存储与扫描编号

manifest 默认位于 `~/.local/state/vman-py/manifest.json`；设置
`XDG_STATE_HOME` 时使用该目录下的 `vman-py/manifest.json`。SQLite 数据库
保存在 manifest 旁，文件名追加 `.sqlite3`，例如 `manifest.json.sqlite3`。
首次使用时自动创建所需目录和数据库。使用同一个 manifest 路径即可在下次运行时
继续编号并访问同一份环境库存；使用不同路径可以维护不同的库存。

manifest 中保存最后分配的编号，例如：

```json
{
  "last_scan_id": 3
}
```

每次 `scan` 开始时先递增并持久化编号，使用独立锁文件和原子替换写入。
扫描失败后该编号也不会复用，因此编号可能有间隔。
`list`、`check` 和 `list --fresh` 不分配扫描编号，也不发现新环境。

## 状态与错误处理

| 环境状态 | 含义 |
| --- | --- |
| `LIVE` | 对应的 `pyvenv.cfg` 文件存在 |
| `MISS` | 环境目录或其中的 `pyvenv.cfg` 文件已不存在 |

检查只验证存在状态，不运行 Python 解释器。重新出现的环境会恢复为 `LIVE`。
检查遇到权限等错误时写入日志并跳过该条，保留原有状态。

扫描遇到目录或配置文件权限不足时，记录日志并跳过，状态仍为 `SUCCESS`。
子目录或配置文件在扫描期间消失，也按普通跳过处理。

根目录不存在或不是目录、I/O 故障、配置损坏以及线程任务异常会将扫描标记为 `FAILED`。
能继续处理的目录和配置仍会被扫描；成功解析的环境仍会入库。
扫描记录与环境更新在同一事务中保存。没有这些故障时，扫描状态为 `SUCCESS`，
包括未发现环境以及仅因权限跳过部分目录的扫描。

CLI 尚未提供并发数参数，该验收项保留在 [#5](https://github.com/Aumnertic/vman-py/issues/5)。

## 扫描日志

扫描和检查日志仅写入数据目录的 `logs/scan.log`，不打印到终端。
默认路径为 `~/.local/state/vman-py/logs/scan.log`，也遵循 `XDG_STATE_HOME`。
指定 `-m ./state/manifest.json` 时，日志位于 `./state/logs/scan.log`。

日志包含扫描编号、根目录、起止事件、结果状态、发现数量、检查汇总、
跳过路径和故障原因；异常的 traceback 也保存在日志中。
每个日志文件最大 5 MiB，保留 3 个轮转备份。终端显示命令汇总和环境列表。

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 运行失败，或扫描状态为 `FAILED` |
| `2` | 命令行参数错误 |
| `130` | 用户中断运行 |

## 开发与贡献

开发环境、验证命令及贡献流程见 [CONTRIBUTE.md](CONTRIBUTE.md)。

## 许可证

本项目使用 [MIT 协议](LICENSE)。
