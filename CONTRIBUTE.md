# 贡献指南

欢迎提交问题报告、文档改进和代码修改。开始较大的变更前，可以先在 issue 中说明
要解决的问题及预期行为，便于讨论范围。

## 开发环境

需要 Python 3.14 或更新版本，以及 uv。

```sh
git clone https://github.com/Aumnertic/vman-py.git
cd vman-py
uv sync --locked
git switch -c your-change
```

本地运行 CLI：

```sh
uv run python main.py --help
uv run vman scan ./sample -m ./local-state/manifest.json
uv run vman list --fresh -m ./local-state/manifest.json
```

测试数据使用临时目录；手动验证也可以指定独立的 manifest 路径，方便观察扫描编号
和库存变化。manifest、锁文件及 SQLite 数据库是运行数据，提交时请只选择源码、
文档和必要配置。

## 代码组织

| 位置 | 职责 |
| --- | --- |
| `main.py`、`src/vman_py/__main__.py` | 调用统一 CLI 入口 |
| `src/vman_py/cli/cli.py` | 命令参数模型、分发及输出 |
| `src/vman_py/cli/argly.py` | 根据 Pydantic 字段生成参数，并校验解析结果 |
| `src/vman_py/core/service.py` | 封装 list、check、scan 的业务流程和连接生命周期 |
| `src/vman_py/core/scan.py` | 环境发现、配置解析及已有环境检查 |
| `src/vman_py/core/scan_result_converter.py` | 将扫描结果转换为 schema 对象 |
| `src/vman_py/core/inventory.py` | SQLite 初始化、查询、更新及扫描记录保存 |
| `src/vman_py/core/manifest.py` | 持久化分配扫描编号 |
| `src/vman_py/core/schema.py`、`model.py` | 库存 schema 和扫描环境模型 |
| `tests/` | 参数解析、扫描、持久化及 CLI 集成测试 |

增加命令时将业务流程放在 service 层，数据库读写放在 inventory 层。
扫描器不调用转换类或承担环境入库；环境 ID 由数据库生成，扫描 ID 由 manifest 分配。
修改入库流程时，保留扫描记录与环境更新的事务一致性。

## 验证修改

测试使用标准库 unittest：

```sh
uv run python -m unittest discover -s tests -v
```

Ruff 和 ty 可以通过 uvx 运行：

```sh
uvx ruff check src tests main.py
uvx ruff format --check src tests main.py
uvx ty check src
git diff --check
```

需要格式化时运行 `uvx ruff format src tests main.py`。
影响数据写入、编号分配或命令行为的修改应验证正常情况及相关失败场景。
修改依赖时同步更新 `pyproject.toml` 和 `uv.lock`，修改 CLI 时更新帮助说明和 README 示例。
修改打包配置时可运行 `uv build` 检查 wheel 和源码包。

## 提交 issue 或 pull request

问题报告请包含执行命令、预期结果、实际输出，以及操作系统和 Python 版本。
如果可以复现，提供最小的目录结构或配置样例；提交日志前移除私人路径及敏感信息。

pull request 请说明解决的问题、修改后的行为和已经运行的验证。
有相关 issue 时附上编号，并逐项核对其验收标准；部分完成时说明剩余工作。
提交前检查 diff，保持改动围绕一个明确的问题，使用能说明修改目的的提交信息。

## 许可证

提交到本项目的贡献使用与项目相同的 [MIT 协议](LICENSE)。
