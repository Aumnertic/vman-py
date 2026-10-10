import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Self

from .inventory import Inventory
from .scan import PyEnvScanner, ScanResult
from .scan_result_converter import ScanResultConverter
from .schema import Environment


class VmanService:
    """封装库存查询、检查和扫描入库，存储位置由 manifest 路径决定。"""

    def __init__(self, manifest_path: str | Path | None = None):
        self.scanner = PyEnvScanner(manifest_path)
        manifest = self.scanner.manifest.path
        self.db_path = manifest.with_name(f"{manifest.name}.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        try:
            Inventory.init_db(self.conn)
        except sqlite3.Error:
            self.conn.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.conn.close()
        self.scanner.close()

    async def list_envs(self, fresh: bool = False) -> list[Environment]:
        if fresh:
            await self.check()
        return Inventory.list_envs(self.conn)

    async def check(self) -> list[Environment]:
        return await self.scanner.check(self.conn)

    async def scan(self, path: str | Path = "~") -> ScanResult:
        await self.check()
        result = await self.scanner.scan(str(path))
        try:
            scan, environments = ScanResultConverter.convert(result)
            with self.conn:
                self.conn.execute("BEGIN")
                Inventory.save_scan(self.conn, scan)
                Inventory.upsert_envs(self.conn, environments)
        except Exception:
            self.scanner.logger.exception("扫描入库失败 scan_id=%s", result.scan_id)
            raise
        self.scanner.logger.info("扫描入库完成 scan_id=%s", result.scan_id)
        return result
