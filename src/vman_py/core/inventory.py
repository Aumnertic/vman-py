import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .model import EnvironmentStatus
from .schema import Environment, Scan


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """复用调用方的事务；没有外层事务时自行提交或回滚。"""
    if conn.in_transaction:
        yield
    else:
        with conn:
            yield


class Inventory:
    @staticmethod
    def init_db(conn: sqlite3.Connection) -> None:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS environments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,

            python_executable TEXT,
            python_version TEXT,
            python_home TEXT,
            manager TEXT,

            status TEXT NOT NULL DEFAULT 'LIVE',

            discovered_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            last_verified_at INTEGER,

            first_seen_scan_id INTEGER,
            last_seen_scan_id INTEGER,

            size_bytes INTEGER,
            size_updated_at INTEGER
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS scan(
            id INTEGER PRIMARY KEY,
            root TEXT NOT NULL,

            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            status INTEGER NOT NULL DEFAULT 1,

            envs_found INTEGER
        );
        """)
        conn.commit()

    @staticmethod
    def upsert_envs(conn: sqlite3.Connection, envs: Iterable[Environment]) -> None:
        """按路径新增或更新环境；ID 及首次发现信息由数据库保留。"""
        with _transaction(conn):
            conn.executemany(
                """
                INSERT INTO environments (
                    path, python_executable, python_version, python_home, manager,
                    status, discovered_at, last_seen_at, last_verified_at,
                    first_seen_scan_id, last_seen_scan_id, size_bytes, size_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    python_executable = excluded.python_executable,
                    python_version = excluded.python_version,
                    python_home = excluded.python_home,
                    manager = excluded.manager,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    last_verified_at = COALESCE(
                        excluded.last_verified_at, environments.last_verified_at
                    ),
                    last_seen_scan_id = COALESCE(
                        excluded.last_seen_scan_id, environments.last_seen_scan_id
                    ),
                    size_bytes = COALESCE(excluded.size_bytes, environments.size_bytes),
                    size_updated_at = COALESCE(
                        excluded.size_updated_at, environments.size_updated_at
                    )
                """,
                (
                    (
                        str(env.path),
                        str(env.python_executable) if env.python_executable else None,
                        env.python_version,
                        str(env.python_home) if env.python_home else None,
                        env.manager,
                        env.status.name,
                        env.discovered_at,
                        env.last_seen_at,
                        env.last_verified_at,
                        env.first_seen_scan_id,
                        env.last_seen_scan_id,
                        env.size_bytes,
                        env.size_updated_at,
                    )
                    for env in envs
                ),
            )

    @staticmethod
    def list_envs(
        conn: sqlite3.Connection, status: EnvironmentStatus | None = None
    ) -> list[Environment]:
        query = """
            SELECT id, path, python_executable, python_version, python_home, manager,
                   status, discovered_at, last_seen_at, last_verified_at,
                   first_seen_scan_id, last_seen_scan_id, size_bytes, size_updated_at
            FROM environments
        """
        parameters = () if status is None else (status.name,)
        if status is not None:
            query += " WHERE status = ?"
        query += " ORDER BY id"
        rows = conn.execute(query, parameters)
        return [
            Environment(
                id=row[0],
                path=Path(row[1]),
                python_executable=Path(row[2]) if row[2] is not None else None,
                python_version=row[3],
                python_home=Path(row[4]) if row[4] is not None else None,
                manager=row[5],
                status=EnvironmentStatus[row[6]],
                discovered_at=row[7],
                last_seen_at=row[8],
                last_verified_at=row[9],
                first_seen_scan_id=row[10],
                last_seen_scan_id=row[11],
                size_bytes=row[12],
                size_updated_at=row[13],
            )
            for row in rows
        ]

    @staticmethod
    def update_env_statuses(
        conn: sqlite3.Connection, envs: Iterable[Environment]
    ) -> None:
        """只更新已有环境的状态和检查时间，保留发现信息及扫描编号。"""
        with _transaction(conn):
            conn.executemany(
                """
                UPDATE environments SET status = ?, last_verified_at = ? WHERE id = ?
                """,
                ((env.status.name, env.last_verified_at, env.id) for env in envs),
            )

    @staticmethod
    def save_scan(conn: sqlite3.Connection, scan: Scan) -> int:
        """保存扫描记录并返回 ID，可用于环境的 first/last_seen_scan_id。"""
        with _transaction(conn):
            cursor = conn.execute(
                """
                INSERT INTO scan (id, root, started_at, finished_at, status, envs_found)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    root = excluded.root,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    envs_found = excluded.envs_found
                """,
                (
                    scan.id,
                    str(scan.root),
                    scan.started_at,
                    scan.finished_at,
                    scan.status.value,
                    scan.environments_found,
                ),
            )
        if scan.id is not None:
            return scan.id
        assert cursor.lastrowid is not None
        return cursor.lastrowid
