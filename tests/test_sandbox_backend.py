import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kernel.bus import EventBus
from openshell import compat
from openshell.executor import SafeExecutor
from openshell.sandbox_backend import OpenShellExecutor


def make_info(available=True, version="0.4.2"):
    return compat.OpenShellInfo(available=available, version=version,
                                cli_path="/usr/local/bin/openshell",
                                detail="ok")


def _build(sandbox: Path, info, **kw):
    from openshell import SecretVault, SecurityPolicy
    policy = SecurityPolicy(["python"], [sandbox], sandbox)
    return OpenShellExecutor(policy, SecretVault(), EventBus(),
                             info=info, timeout=10, **kw)


class BackendSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_when_runtime_present(self):
        backend = _build(Path(tempfile.mkdtemp()), make_info())
        self.assertTrue(await backend.ensure_ready())
        self.assertEqual(backend.describe_backend()["backend"], "openshell")

    async def test_not_ready_when_absent(self):
        backend = _build(Path(tempfile.mkdtemp()), make_info(available=False))
        self.assertFalse(await backend.ensure_ready())
        self.assertEqual(backend.describe_backend()["backend"],
                         "policy-fallback")

    async def test_not_ready_below_minimum(self):
        backend = _build(Path(tempfile.mkdtemp()),
                         make_info(version="0.0.1"))
        self.assertFalse(await backend.ensure_ready())

    async def test_lazy_probe_when_no_info_injected(self):
        backend = _build(Path(tempfile.mkdtemp()), None)

        async def fake_probe():
            return make_info()
        with mock.patch.object(compat, "probe_version", fake_probe):
            self.assertTrue(await backend.ensure_ready())
        self.assertEqual(backend.info.version, "0.4.2")
        # the attempted flag is set: a later downgrade does not re-probe
        backend._info = make_info(available=False)
        self.assertFalse(await backend.ensure_ready())


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def _backend(self, info):
        backend = _build(Path(tempfile.mkdtemp()), info)
        captured = {}

        async def fake_spawn(argv, program, args, timeout, cwd):
            captured["argv"] = argv
            from openshell.executor import ExecResult
            return ExecResult(program=program, args=tuple(args),
                              exit_code=0, stdout="ran", stderr="")

        backend._spawn_and_collect = fake_spawn
        return backend, captured

    async def test_routes_through_sandbox_when_ready(self):
        backend, captured = await self._backend(make_info())
        result = await backend.run("python", ["-c", "print(1)"])
        self.assertTrue(result.ok)
        prefix = captured["argv"][:6]
        self.assertEqual(prefix, ["openshell", "sandbox", "exec",
                                  "--sandbox", "sparkagent", "--"])
        self.assertEqual(backend.backend_stats["sandboxed"], 1)
        self.assertEqual(backend.backend_stats["fallback"], 0)

    async def test_falls_back_without_runtime(self):
        backend, captured = await self._backend(make_info(available=False))
        result = await backend.run("python", ["-c", "print(1)"])
        self.assertTrue(result.ok)
        self.assertIn("python", captured["argv"][0].lower())
        self.assertNotIn("openshell", captured["argv"])
        self.assertEqual(backend.backend_stats["fallback"], 1)

    async def test_policy_blocks_before_any_spawn(self):
        backend, captured = await self._backend(make_info())
        result = await backend.run("python", ["-c", "format C: /y"])
        self.assertIsNotNone(result.blocked_reason)
        self.assertNotIn("argv", captured)
        self.assertEqual(backend.backend_stats["sandboxed"], 0)

    async def test_custom_sandbox_name(self):
        backend, captured = await self._backend(make_info())
        backend.sandbox_name = "lab-agent"
        await backend.run("python", ["--version"])
        self.assertEqual(captured["argv"][4], "lab-agent")

    async def test_describe_backend_shape(self):
        backend = _build(Path(tempfile.mkdtemp()), make_info())
        payload = backend.describe_backend()
        for key in ("backend", "sandbox", "runtime", "sandboxed",
                    "fallback"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
