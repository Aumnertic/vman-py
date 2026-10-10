# vman-py

扫描、记录和检查 Python 虚拟环境。

```sh
uv sync
uv run vman scan                     # 默认扫描 ~，先检查已有环境
uv run vman scan ./projects          # 扫描指定目录
uv run vman list                     # 显示数据库中已有的环境
uv run vman list --fresh             # 先检查存在状态，再显示完整列表
uv run vman check                    # 检查已有环境并保存 LIVE/MISS 状态
```

三个命令均支持 `-m MANIFEST_PATH` 或 `--manifest MANIFEST_PATH`：

```sh
uv run vman scan ./projects -m ./state/manifest.json
uv run vman list --manifest ./state/manifest.json
uv run vman check -m ./state/manifest.json
```

manifest 默认位于 `~/.local/state/vman-py/manifest.json`；设置
`XDG_STATE_HOME` 时使用该目录下的 `vman-py/manifest.json`。SQLite 数据库
保存在 manifest 旁，文件名追加 `.sqlite3`，例如 `manifest.json.sqlite3`。
使用同一个 manifest 路径即可在下次运行时继续编号并访问同一份环境库存。

`scan` 先检查全部已有环境，再扫描指定目录，将扫描记录和成功解析的环境
在同一事务中保存。缺失 `pyvenv.cfg` 的环境标记为 `MISS`，文件仍存在的
标记为 `LIVE`；检查只验证存在状态，不运行 Python 解释器。
`check` 和 `list --fresh` 不创建扫描编号，也不发现新环境。

退出码：成功为 `0`，运行失败或扫描中有配置被跳过为 `1`，参数错误为 `2`。
也可使用 `uv run vman-py` 或 `uv run python -m vman_py` 调用同一入口。
