"""ops.preflight — combined config/brain/disk checks with exit codes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kernel.config import Config
from ops.preflight import main, preflight_all


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
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(True)):
            checks = await preflight_all(data_dir)
        names = {c["name"] for c in checks}
        self.assertEqual(names, {"config", "brain", "disk"})
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


class PreflightMainTests(unittest.TestCase):
    def test_exit_0_all_clear(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(True)):
            self.assertEqual(main(["--data-dir", str(data_dir)]), 0)

    def test_exit_1_when_brain_down(self):
        data_dir = Path(tempfile.mkdtemp())
        with patch("brain.bridge.Brain", lambda *a, **k: _FakeBrain(False)):
            self.assertEqual(main(["--data-dir", str(data_dir)]), 1)

    def test_exit_2_when_config_unreadable(self):
        self.assertEqual(main(["--data-dir", str(Path(tempfile.mkdtemp())),
                               "--config", "Z:/no/such.yaml"]), 2)


if __name__ == "__main__":
    unittest.main()
