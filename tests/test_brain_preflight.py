"""Brain preflight CLI — per-tier health report and exit codes."""

import unittest
from unittest.mock import patch

from brain.bridge import BrainResponse, Tier
from kernel.config import Config


class _FakeBrain:
    def __init__(self, local_ok, remote_ok, chat_error=None):
        self._health = {
            "local": {"ok": local_ok, "detail": "ok" if local_ok else "down",
                      "duration_ms": 0.0, "model": "fake-local"},
            "remote": {"ok": remote_ok,
                       "detail": "ok" if remote_ok else "down",
                       "duration_ms": 0.0, "model": "fake-remote"},
            "stats": {}}
        self._chat_error = chat_error
        self.closed = False

    async def health(self):
        return self._health

    async def chat(self, messages, **_kwargs):
        if self._chat_error:
            raise RuntimeError(self._chat_error)
        return BrainResponse(text="ok", tier=Tier.LOCAL, model="fake-local",
                             elapsed=0.01)

    async def close(self):
        self.closed = True


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_healthy_when_local_ok(self):
        from brain.preflight import preflight
        fake = _FakeBrain(local_ok=True, remote_ok=False)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            report = await preflight(Config({}), with_chat=True)
        self.assertTrue(report["healthy"])
        self.assertTrue(report["chat"]["ok"])
        self.assertTrue(fake.closed)

    async def test_preflight_chat_carries_duration_ms(self):
        from brain.preflight import preflight
        fake = _FakeBrain(local_ok=True, remote_ok=False)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            report = await preflight(Config({}), with_chat=True)
        self.assertGreaterEqual(report["chat"]["duration_ms"], 0)
        # per-check durations ride the tier entries too (from Brain.health)
        for tier in ("local", "remote"):
            self.assertIn("duration_ms", report[tier])

    async def test_preflight_unhealthy_when_all_down(self):
        from brain.preflight import preflight
        fake = _FakeBrain(local_ok=False, remote_ok=False,
                          chat_error="all LLM tiers failed")
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            report = await preflight(Config({}), with_chat=True)
        self.assertFalse(report["healthy"])
        self.assertFalse(report["chat"]["ok"])

    async def test_preflight_remote_only_ok(self):
        from brain.preflight import preflight
        fake = _FakeBrain(local_ok=False, remote_ok=True)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            report = await preflight(Config({}))
        self.assertTrue(report["healthy"])
        self.assertNotIn("chat", report)

    async def test_chat_failure_marks_unhealthy(self):
        from brain.preflight import preflight
        fake = _FakeBrain(local_ok=True, remote_ok=False,
                          chat_error="budget veto")
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            report = await preflight(Config({}), with_chat=True)
        self.assertFalse(report["healthy"])


class PreflightMainTests(unittest.TestCase):
    def test_missing_config_exits_2(self):
        from brain.preflight import main
        self.assertEqual(main(["--config", "Z:/no/such/config.yaml"]), 2)

    def test_exit_1_when_no_tier_usable(self):
        from brain.preflight import main
        fake = _FakeBrain(local_ok=False, remote_ok=False)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            self.assertEqual(main([]), 1)

    def test_text_output_shows_durations(self):
        import contextlib
        import io
        from brain.preflight import main
        fake = _FakeBrain(local_ok=True, remote_ok=False)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                main([])
        self.assertIn("ms)", buffer.getvalue())

    def test_exit_0_when_local_ok(self):
        from brain.preflight import main
        fake = _FakeBrain(local_ok=True, remote_ok=False)
        with patch("brain.bridge.Brain", lambda *a, **k: fake):
            self.assertEqual(main([]), 0)


if __name__ == "__main__":
    unittest.main()
