import asyncio
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from vman_py.core.inventory import Inventory
from vman_py.core.model import EnvironmentStatus, PyEnv
from vman_py.core.scan import PyEnvScanner, ScanResult, ScanStatus
from vman_py.core.scan_result_converter import ScanResultConverter


class ScanInventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.manifest_path = self.root / "state/manifest.json"
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        Inventory.init_db(self.conn)

    def make_cfg(self, name="venv", content="home = /base/python\nversion = 3.14.6\n"):
        cfg = self.root / name / "pyvenv.cfg"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(content, encoding="utf-8")
        return cfg

    def scan(self):
        return asyncio.run(
            PyEnvScanner(manifest_path=self.manifest_path).scan(str(self.root))
        )

    def test_scan_convert_and_persist(self):
        cfg = self.make_cfg()
        python = cfg.parent / "bin/python"
        python.parent.mkdir()
        base_python = self.root / "base-python"
        base_python.touch()
        python.symlink_to(base_python)
        # 保持原来的行为：发现环境后不继续扫描该环境下的目录。
        self.make_cfg("venv/nested")

        result = self.scan()
        self.assertEqual(result.root, self.root)
        self.assertEqual(result.status, ScanStatus.SUCCESS)
        self.assertLessEqual(result.started_at, result.finished_at)
        self.assertEqual(len(result.environments), 1)
        self.assertEqual(result.environments[0].cfg_path, cfg)

        scan, envs = ScanResultConverter.convert(result)
        scan_id = Inventory.save_scan(self.conn, scan)
        self.assertEqual(scan_id, result.scan_id)
        self.assertEqual(scan.id, scan_id)
        self.assertEqual(scan.environments_found, 1)
        self.assertEqual(envs[0].python_executable, python)
        self.assertEqual(envs[0].python_home, Path("/base/python"))
        self.assertEqual(envs[0].python_version, "3.14.6")
        self.assertEqual(envs[0].manager, "venv")
        self.assertIsNone(envs[0].last_verified_at)
        self.assertIsNone(envs[0].id)

        Inventory.upsert_envs(self.conn, envs)
        stored = Inventory.list_envs(self.conn)
        self.assertEqual(stored, [replace(envs[0], id=stored[0].id)])
        self.assertIsInstance(stored[0].id, int)
        self.assertEqual(stored[0].first_seen_scan_id, scan_id)

    def test_bad_config_is_printed_and_skipped(self):
        good = self.make_cfg("good")
        bad = self.make_cfg("bad", "invalid config\n")
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.scan()
        self.assertEqual(result.status, ScanStatus.FAILED)
        self.assertEqual([env.cfg_path for env in result.environments], [good])
        self.assertIn(str(bad), output.getvalue())
        self.assertIn("跳过配置", output.getvalue())
        scan, envs = ScanResultConverter.convert(result)
        self.assertEqual(scan.environments_found, 1)
        self.assertEqual(len(envs), 1)

    def test_read_errors_are_printed_and_skipped(self):
        good = self.make_cfg("good")
        missing = self.root / "missing/pyvenv.cfg"
        undecodable = self.make_cfg("undecodable")
        undecodable.write_bytes(b"\xff")
        output = io.StringIO()
        with redirect_stdout(output):
            envs, status = asyncio.run(
                PyEnvScanner()._cfg_handle([missing, good, undecodable])
            )
        self.assertEqual(status, ScanStatus.FAILED)
        self.assertEqual([env.cfg_path for env in envs], [good])
        self.assertIn(str(missing), output.getvalue())
        self.assertIn(str(undecodable), output.getvalue())

    def test_empty_scan_is_successful(self):
        result = self.scan()
        self.assertEqual(result.environments, [])
        self.assertEqual(result.status, ScanStatus.SUCCESS)
        scan, envs = ScanResultConverter.convert(result)
        self.assertEqual(scan.environments_found, 0)
        Inventory.upsert_envs(self.conn, envs)
        self.assertEqual(Inventory.list_envs(self.conn), [])

    def test_scan_id_survives_scanner_restart(self):
        first = self.scan()
        second = self.scan()
        self.assertEqual(first.scan_id, 1)
        self.assertEqual(second.scan_id, 2)
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["last_scan_id"], 2)
        scan, _ = ScanResultConverter.convert(second)
        self.assertEqual(scan.id, second.scan_id)

    def test_scan_failure_does_not_reuse_id(self):
        with self.assertRaises(FileNotFoundError):
            asyncio.run(
                PyEnvScanner(self.manifest_path).scan(str(self.root / "missing"))
            )
        self.assertEqual(self.scan().scan_id, 2)

    def test_converter_supports_windows_layout_and_managers(self):
        cfg = self.make_cfg(content="version = 3.14.6\nuv = 0.9\n")
        python = cfg.parent / "Scripts/python.exe"
        python.parent.mkdir()
        python.touch()
        result = self.scan()
        _, envs = ScanResultConverter.convert(result)
        self.assertEqual(envs[0].python_executable, python)
        self.assertEqual(envs[0].manager, "uv")
        self.assertIsNone(envs[0].python_home)
        result.environments[0].__dict__.pop("uv")
        result.environments[0].virtualenv = "20.0"
        _, envs = ScanResultConverter.convert(result)
        self.assertEqual(envs[0].manager, "virtualenv")

    def test_converter_requires_config_path(self):
        result = ScanResult(1, [PyEnv()], self.root, 100, 101, ScanStatus.SUCCESS)
        with self.assertRaisesRegex(ValueError, "cfg_path"):
            ScanResultConverter.convert(result)

    def test_upsert_preserves_identity_and_first_seen_metadata(self):
        self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())
        original = replace(
            envs[0],
            discovered_at=100,
            last_seen_at=100,
            last_verified_at=100,
            size_bytes=123,
            size_updated_at=100,
        )
        Inventory.upsert_envs(self.conn, [original])
        original_id = Inventory.list_envs(self.conn)[0].id
        updated = replace(
            envs[0],
            id=999,
            python_version="3.15",
            discovered_at=200,
            last_seen_at=200,
            first_seen_scan_id=2,
            last_seen_scan_id=2,
        )
        Inventory.upsert_envs(self.conn, [updated])
        stored = Inventory.list_envs(self.conn)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].id, original_id)
        self.assertEqual(stored[0].discovered_at, 100)
        self.assertEqual(stored[0].first_seen_scan_id, 1)
        self.assertEqual(stored[0].last_seen_scan_id, 2)
        self.assertEqual(stored[0].last_seen_at, 200)
        self.assertEqual(stored[0].python_version, "3.15")
        self.assertEqual(stored[0].size_bytes, 123)
        self.assertEqual(stored[0].size_updated_at, 100)
        self.assertEqual(stored[0].last_verified_at, 100)

    def test_environment_id_is_autoincremented(self):
        self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())
        Inventory.upsert_envs(self.conn, envs)
        first_id = Inventory.list_envs(self.conn)[0].id
        with self.conn:
            self.conn.execute("DELETE FROM environments")
        Inventory.upsert_envs(self.conn, envs)
        self.assertGreater(Inventory.list_envs(self.conn)[0].id, first_id)

    def test_list_filters_status_without_changing_connection(self):
        self.make_cfg("live")
        self.make_cfg("missing")
        _, envs = ScanResultConverter.convert(self.scan())
        envs[1] = replace(envs[1], status=EnvironmentStatus.MISS)
        Inventory.upsert_envs(self.conn, envs)
        self.conn.row_factory = sqlite3.Row
        missing = Inventory.list_envs(self.conn, EnvironmentStatus.MISS)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].path, envs[1].path)
        self.assertEqual(missing[0].status, EnvironmentStatus.MISS)
        self.assertIs(self.conn.row_factory, sqlite3.Row)

    def test_upsert_rolls_back_partial_batch(self):
        self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())

        def broken_batch():
            yield envs[0]
            raise RuntimeError("batch failed")

        with self.assertRaisesRegex(RuntimeError, "batch failed"):
            Inventory.upsert_envs(self.conn, broken_batch())
        self.assertEqual(Inventory.list_envs(self.conn), [])

    def test_check_marks_missing_config_and_preserves_environment_metadata(self):
        self.make_cfg("live")
        missing = self.make_cfg("missing")
        _, envs = ScanResultConverter.convert(self.scan())
        Inventory.upsert_envs(self.conn, envs)
        originals = {env.path: env for env in Inventory.list_envs(self.conn)}
        missing.unlink()  # 环境目录仍在，但已经没有 pyvenv.cfg。

        checked = asyncio.run(PyEnvScanner(self.manifest_path).check(self.conn))
        stored = Inventory.list_envs(self.conn)
        self.assertEqual(checked, stored)
        self.assertEqual(len(stored), 2)
        for env in stored:
            expected_status = (
                EnvironmentStatus.MISS
                if env.path == missing.parent
                else EnvironmentStatus.LIVE
            )
            self.assertEqual(env.status, expected_status)
            self.assertIsNotNone(env.last_verified_at)
            self.assertEqual(
                env,
                replace(
                    originals[env.path],
                    status=expected_status,
                    last_verified_at=env.last_verified_at,
                ),
            )
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["last_scan_id"], 1)

    def test_check_marks_deleted_environment_missing(self):
        cfg = self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())
        Inventory.upsert_envs(self.conn, envs)
        cfg.unlink()
        cfg.parent.rmdir()
        asyncio.run(PyEnvScanner(self.manifest_path).check(self.conn))
        self.assertEqual(
            Inventory.list_envs(self.conn)[0].status, EnvironmentStatus.MISS
        )

    def test_check_restores_existing_environment_to_live(self):
        self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())
        Inventory.upsert_envs(
            self.conn, [replace(envs[0], status=EnvironmentStatus.MISS)]
        )
        asyncio.run(PyEnvScanner(self.manifest_path).check(self.conn))
        self.assertEqual(
            Inventory.list_envs(self.conn)[0].status, EnvironmentStatus.LIVE
        )

    def test_check_skips_permission_errors(self):
        cfg = self.make_cfg()
        _, envs = ScanResultConverter.convert(self.scan())
        Inventory.upsert_envs(self.conn, envs)
        original = Inventory.list_envs(self.conn)
        output = io.StringIO()
        with (
            patch("vman_py.core.scan.Path.stat", side_effect=PermissionError("denied")),
            redirect_stdout(output),
        ):
            checked = asyncio.run(PyEnvScanner(self.manifest_path).check(self.conn))
        self.assertEqual(checked, [])
        self.assertEqual(Inventory.list_envs(self.conn), original)
        self.assertIn(str(cfg.parent), output.getvalue())
        self.assertIn("denied", output.getvalue())

    def test_check_empty_inventory_does_not_allocate_scan_id(self):
        checked = asyncio.run(PyEnvScanner(self.manifest_path).check(self.conn))
        self.assertEqual(checked, [])
        self.assertFalse(self.manifest_path.exists())

    def test_save_scan_updates_existing_record(self):
        scan, _ = ScanResultConverter.convert(self.scan())
        scan_id = Inventory.save_scan(self.conn, scan)
        updated = replace(
            scan, id=scan_id, status=ScanStatus.FAILED, environments_found=3
        )
        self.assertEqual(Inventory.save_scan(self.conn, updated), scan_id)
        row = self.conn.execute("SELECT status, envs_found FROM scan").fetchone()
        self.assertEqual(row, (ScanStatus.FAILED.value, 3))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM scan").fetchone()[0], 1
        )


if __name__ == "__main__":
    unittest.main()
