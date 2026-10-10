import asyncio
import errno
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel, Field

from vman_py.cli.argly import parse
from vman_py.cli.cli import ScanArgs, build_parser, main
from vman_py.core.config import DEFAULT_MANIFEST_PATH
from vman_py.core.inventory import Inventory
from vman_py.core.model import EnvironmentStatus
from vman_py.core.service import VmanService


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.scan_root = self.root / "projects"
        self.scan_root.mkdir()
        self.manifest = self.root / "state/manifest.json"

    def make_cfg(self, name="venv", content="home = /python\nversion = 3.14.6\n"):
        cfg = self.scan_root / name / "pyvenv.cfg"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(content, encoding="utf-8")
        return cfg

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([*args, "-m", str(self.manifest)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_scan_paths_are_optional_and_aliases_work(self):
        parser = build_parser()
        arguments = vars(parser.parse_args(["scan"]))
        arguments.pop("command")
        defaults = ScanArgs.model_validate(arguments)
        self.assertEqual(defaults.path, Path("~"))
        self.assertEqual(defaults.manifest, DEFAULT_MANIFEST_PATH)
        for flag in ("-m", "--manifest"):
            with self.subTest(flag=flag):
                arguments = vars(parser.parse_args(["scan", flag, str(self.manifest)]))
                arguments.pop("command")
                parsed = ScanArgs.model_validate(arguments)
                self.assertEqual(parsed.path, Path("~"))
                self.assertEqual(parsed.manifest, self.manifest)

    def test_scan_and_list_persist_across_service_instances(self):
        cfg = self.make_cfg()
        code, output, error = self.run_cli("scan", str(self.scan_root))
        self.assertEqual(code, 0, error)
        self.assertIn("扫描 #1", output)
        self.assertIn("1 个环境", output)
        code, output, error = self.run_cli("list")
        self.assertEqual(code, 0, error)
        self.assertIn(str(cfg.parent), output)
        self.assertIn("LIVE", output)
        self.assertIn("3.14.6", output)
        self.assertIn("venv", output)
        with VmanService(self.manifest) as service:
            self.assertEqual(
                service.conn.execute("SELECT COUNT(*) FROM scan").fetchone()[0], 1
            )

    def test_plain_list_uses_cached_state_and_fresh_list_checks(self):
        cfg = self.make_cfg()
        self.run_cli("scan", str(self.scan_root))
        cfg.unlink()
        code, cached, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("LIVE", cached)
        code, fresh, _ = self.run_cli("list", "--fresh")
        self.assertEqual(code, 0)
        self.assertIn("MISS", fresh)
        code, saved, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("MISS", saved)
        self.assertEqual(
            json.loads(self.manifest.read_text(encoding="utf-8"))["last_scan_id"], 1
        )

    def test_check_command_updates_existing_environments(self):
        cfg = self.make_cfg()
        self.run_cli("scan", str(self.scan_root))
        cfg.unlink()
        code, output, error = self.run_cli("check")
        self.assertEqual(code, 0, error)
        self.assertIn("1 个 MISS", output)
        self.assertIn(str(cfg.parent), output)
        with VmanService(self.manifest) as service:
            stored = Inventory.list_envs(service.conn)
            self.assertEqual(stored[0].status, EnvironmentStatus.MISS)
            self.assertIsNotNone(stored[0].last_verified_at)

    def test_scan_checks_environments_outside_requested_root_first(self):
        cfg = self.make_cfg()
        self.run_cli("scan", str(self.scan_root))
        cfg.unlink()
        other_root = self.root / "other"
        other_root.mkdir()
        code, output, error = self.run_cli("scan", str(other_root))
        self.assertEqual(code, 0, error)
        self.assertIn("扫描 #2", output)
        with VmanService(self.manifest) as service:
            stored = Inventory.list_envs(service.conn)
            self.assertEqual(stored[0].status, EnvironmentStatus.MISS)
            self.assertEqual(stored[0].last_seen_scan_id, 1)

    def test_empty_inventory_does_not_create_manifest(self):
        code, output, error = self.run_cli("list")
        self.assertEqual(code, 0, error)
        self.assertIn("暂无环境", output)
        self.assertFalse(self.manifest.exists())
        code, _, error = self.run_cli("check")
        self.assertEqual(code, 0, error)
        self.assertFalse(self.manifest.exists())

    def test_manifest_paths_select_separate_inventories(self):
        self.make_cfg()
        self.run_cli("scan", str(self.scan_root))
        another = self.root / "state/other.json"
        with VmanService(another) as service:
            self.assertEqual(asyncio.run(service.list_envs()), [])
            self.assertNotEqual(service.db_path, self.manifest)

    def test_bad_config_returns_failure_but_saves_valid_environments(self):
        self.make_cfg("valid")
        self.make_cfg("invalid", "bad config\n")
        code, output, _ = self.run_cli("scan", str(self.scan_root))
        self.assertEqual(code, 1)
        self.assertNotIn("配置解析失败", output)
        self.assertIn("FAILED", output)
        log = (self.manifest.parent / "logs/scan.log").read_text(encoding="utf-8")
        self.assertIn("配置解析失败", log)
        with VmanService(self.manifest) as service:
            self.assertEqual(len(Inventory.list_envs(service.conn)), 1)
            self.assertEqual(
                service.conn.execute("SELECT status, envs_found FROM scan").fetchone(),
                (2, 1),
            )

    def test_missing_scan_root_returns_error_without_traceback(self):
        code, output, error = self.run_cli("scan", str(self.root / "missing"))
        self.assertEqual(code, 1)
        self.assertEqual(error, "")
        self.assertIn("FAILED", output)
        self.assertNotIn("Traceback", output)
        with VmanService(self.manifest) as service:
            self.assertEqual(
                service.conn.execute("SELECT status, envs_found FROM scan").fetchone(),
                (2, 0),
            )

    def test_directory_errors_are_logged_and_status_is_saved(self):
        cfg = self.make_cfg("good")
        broken = self.scan_root / "broken"
        broken.mkdir()
        original_scandir = os.scandir
        for error, expected_status, expected_code in (
            (PermissionError("denied"), 1, 0),
            (OSError(errno.EIO, "disk failure"), 2, 1),
        ):
            with self.subTest(error=error):

                def broken_scandir(path, error=error):
                    if Path(path) == broken:
                        raise error
                    return original_scandir(path)

                with patch("vman_py.core.scan.os.scandir", side_effect=broken_scandir):
                    code, output, stderr = self.run_cli("scan", str(self.scan_root))
                self.assertEqual(code, expected_code)
                self.assertEqual(stderr, "")
                self.assertNotIn(str(broken), output)
                with VmanService(self.manifest) as service:
                    row = service.conn.execute(
                        "SELECT status, envs_found FROM scan ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    self.assertEqual(row, (expected_status, 1))
                    self.assertEqual(
                        Inventory.list_envs(service.conn)[0].path, cfg.parent
                    )
                log = (self.manifest.parent / "logs/scan.log").read_text(
                    encoding="utf-8"
                )
                self.assertIn(str(broken), log)
                self.assertIn("扫描入库完成", log)

    def test_invalid_arguments_fail_before_opening_inventory(self):
        for args in (
            ["scan", "-m"],
            ["scan", "a", "b"],
            ["list", "--unknown"],
            ["scan", "--fresh"],
        ):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.manifest.parent.exists())

    def test_scan_and_environment_write_roll_back_together(self):
        self.make_cfg()
        original_upsert = Inventory.upsert_envs

        def failing_upsert(conn, envs):
            original_upsert(conn, envs)
            raise sqlite3.IntegrityError("save failed")

        with VmanService(self.manifest) as service:
            with (
                patch.object(Inventory, "upsert_envs", side_effect=failing_upsert),
                self.assertRaises(sqlite3.IntegrityError),
            ):
                asyncio.run(service.scan(self.scan_root))
            self.assertEqual(Inventory.list_envs(service.conn), [])
            self.assertEqual(
                service.conn.execute("SELECT COUNT(*) FROM scan").fetchone()[0], 0
            )

    def test_module_entrypoint_persists_across_processes(self):
        cfg = self.make_cfg()
        for args in (["scan", str(self.scan_root)], ["list"]):
            process = subprocess.run(
                [sys.executable, "-m", "vman_py", *args, "-m", str(self.manifest)],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        self.assertIn(str(cfg.parent), process.stdout)

    def test_xdg_default_is_used_by_list(self):
        state_root = self.root / "xdg"
        process = subprocess.run(
            [sys.executable, "-m", "vman_py", "list"],
            env={**os.environ, "XDG_STATE_HOME": str(state_root)},
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        self.assertIn("暂无环境", process.stdout)
        self.assertTrue((state_root / "vman-py/manifest.json.sqlite3").is_file())
        self.assertFalse((state_root / "vman-py/manifest.json").exists())


class ArglyTests(unittest.TestCase):
    def test_model_validation_with_defaults_optional_position_and_flags(self):
        class Args(BaseModel):
            path: Path = Field(
                default=Path("~"), json_schema_extra={"positional": True}
            )
            count: int = 1
            verbose: bool = False

        self.assertEqual(parse(Args, []).path, Path("~"))
        parsed = parse(Args, ["folder", "--count=3", "--verbose"])
        self.assertEqual(parsed.path, Path("folder"))
        self.assertEqual(parsed.count, 3)
        self.assertTrue(parsed.verbose)
        self.assertFalse(parse(Args, ["--no-verbose"]).verbose)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            parse(Args, ["--count", "invalid"])
        self.assertEqual(error.exception.code, 2)

    def test_required_position_is_supported(self):
        class Args(BaseModel):
            name: str

        self.assertEqual(parse(Args, ["test"]).name, "test")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            parse(Args, [])
        self.assertEqual(error.exception.code, 2)
