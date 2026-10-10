import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vman_py.core.manifest import Manifest


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "state/manifest.json"

    def test_new_instances_continue_numbering_and_preserve_other_fields(self):
        self.assertEqual(Manifest(self.path).next_scan_id(), 1)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["settings"] = {"keep": True}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(Manifest(self.path).next_scan_id(), 2)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"last_scan_id": 2, "settings": {"keep": True}})

    def test_separate_processes_allocate_unique_ids(self):
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "from vman_py.core.manifest import Manifest; "
                        "import sys; print(Manifest(sys.argv[1]).next_scan_id())"
                    ),
                    str(self.path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(8)
        ]
        ids = []
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                ids.append(int(stdout))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait()
        self.assertEqual(sorted(ids), list(range(1, 9)))
        self.assertEqual(Manifest(self.path).next_scan_id(), 9)

    def test_invalid_manifest_is_preserved(self):
        self.path.parent.mkdir(parents=True)
        for content in (
            "{broken",
            "[]",
            '{"last_scan_id": -1}',
            '{"last_scan_id": true}',
            '{"last_scan_id": "1"}',
        ):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises((TypeError, ValueError)):
                    Manifest(self.path).next_scan_id()
                self.assertEqual(self.path.read_text(encoding="utf-8"), content)

    def test_failed_atomic_write_preserves_previous_manifest(self):
        Manifest(self.path).next_scan_id()
        previous = self.path.read_bytes()
        with (
            patch("vman_py.core.manifest.os.replace", side_effect=OSError("failed")),
            self.assertRaises(OSError),
        ):
            Manifest(self.path).next_scan_id()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(Manifest(self.path).next_scan_id(), 2)

    def test_default_path_honors_xdg_state_home(self):
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "from vman_py.core.manifest import Manifest; print(Manifest().path)",
            ],
            env={**os.environ, "XDG_STATE_HOME": str(self.root)},
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        self.assertEqual(
            Path(process.stdout.strip()), self.root / "vman-py/manifest.json"
        )
