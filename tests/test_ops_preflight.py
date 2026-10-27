"""ops.preflight — combined config/brain/disk/backup checks with exit codes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kernel.config import Config
from ops.backup import create_backup
from ops.preflight import _backup_check, main, preflight_all


class _FakeBrain:
    def __init__(self, healthy):
        self._healthy = healthy

    async def health(self):
        return {"local": {"ok": self._healthy, "detail": "ok" if
                          self._healthy else "down", "model": "fake"},
                "remote": {"ok": False, "detail": "down", "model": None},
                "stats": {}}

    async def close(self):
        pass


class PreflightAllTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_clear_when_brain_ok(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(True)), \
             patch("ops.preflight._backup_check",
                   return_value={"ok": True, "detail": "fresh"}):
            checks = await preflight_all(data_dir)
        names = {c["name"] for c in checks}
        self.assertEqual(names, {"config", "brain", "disk", "backup"})
        self.assertTrue(all(c["ok"] for c in checks))

    async def test_brain_down_flags_attention(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(False)):
            checks = await preflight_all(data_dir)
        brain = next(c for c in checks if c["name"] == "brain")
        self.assertFalse(brain["ok"])
        self.assertTrue(next(c for c in checks
                             if c["name"] == "config")["ok"])

    async def test_unreadable_config_skips_brain(self):
        checks = await preflight_all(Path(tempfile.mkdtemp()),
                                     config_path="Z:/no/such.yaml")
        by_name = {c["name"]: c for c in checks}
        self.assertFalse(by_name["config"]["ok"])
        self.assertFalse(by_name["brain"]["ok"])
        self.assertIn("skipped", by_name["brain"]["detail"])
        self.assertNotIn("backup", by_name)   # needs a readable config


class PreflightMainTests(unittest.TestCase):
    def test_exit_0_all_clear(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(True)), \
             patch("ops.preflight._backup_check",
                   return_value={"ok": True, "detail": "fresh"}):
            self.assertEqual(main(["--data-dir", str(data_dir)]), 0)

    def test_exit_1_when_brain_down(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(False)), \
             patch("ops.preflight._backup_check",
                   return_value={"ok": True, "detail": "fresh"}):
            self.assertEqual(main(["--data-dir", str(data_dir)]), 1)

    def test_exit_1_when_backup_stale(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(True)), \
             patch("ops.preflight._backup_check",
                   return_value={"ok": False, "detail": "newest backup 30h old"}):
            self.assertEqual(main(["--data-dir", str(data_dir)]), 1)

    def test_exit_2_when_config_unreadable(self):
        self.assertEqual(main(["--data-dir", str(Path(tempfile.mkdtemp())),
                               "--config", "Z:/no/such.yaml"]), 2)


class BackupCheckTests(unittest.TestCase):
    def test_no_backups_flags(self):
        config = Config({}, root=Path(tempfile.mkdtemp()))
        result = _backup_check(config)
        self.assertFalse(result["ok"])
        self.assertIn("no backups", result["detail"])

    def test_fresh_backup_ok(self):
        root = Path(tempfile.mkdtemp())
        data = root / "data"
        data.mkdir()
        (data / "sparkagent.db").write_bytes(b"x")
        create_backup(data, root / "backups")
        result = _backup_check(Config({}, root=root))
        self.assertTrue(result["ok"])
        self.assertIn("h old", result["detail"])

    def test_stale_backup_flags(self):
        root = Path(tempfile.mkdtemp())
        data = root / "data"
        data.mkdir()
        (data / "sparkagent.db").write_bytes(b"x")
        archive = create_backup(data, root / "backups").archive_path
        stale = archive.stat().st_mtime - 25 * 3600
        os.utime(archive, (stale, stale))
        result = _backup_check(Config({}, root=root))
        self.assertFalse(result["ok"])
        self.assertIn("schedule a create", result["detail"])


if __name__ == "__main__":
    unittest.main()
