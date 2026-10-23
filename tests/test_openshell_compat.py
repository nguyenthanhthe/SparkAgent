import unittest

from openshell import compat


def make_runner(code=0, output="openshell 0.4.2 (gateway ready)"):
    calls = []

    async def runner(argv):
        calls.append(argv)
        return code, output
    return runner, calls


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._original = compat.cli_present
        compat.cli_present = lambda: "/usr/local/bin/openshell"

    def tearDown(self):
        compat.cli_present = self._original

    async def test_detects_version(self):
        runner, calls = make_runner()
        info = await compat.probe_version(runner=runner)
        self.assertTrue(info.available)
        self.assertEqual(info.version, "0.4.2")
        self.assertEqual(calls, [("openshell", "--version")])
        self.assertEqual(info.detail, "ok")

    async def test_nonzero_exit_unavailable(self):
        runner, _ = make_runner(code=1, output="error")
        info = await compat.probe_version(runner=runner)
        self.assertFalse(info.available)
        self.assertIn("exited 1", info.detail)

    async def test_unparseable_version_still_available(self):
        runner, _ = make_runner(output="openshell custom-build")
        info = await compat.probe_version(runner=runner)
        # CLI responded fine; version string simply isn't semver
        self.assertTrue(info.available)
        self.assertEqual(info.version, "")

    async def test_missing_cli_short_circuits(self):
        original = compat.cli_present
        compat.cli_present = lambda: None
        try:
            async def unexpected(argv):  # pragma: no cover
                raise AssertionError("runner must not be called")
            info = await compat.probe_version(runner=unexpected)
            self.assertFalse(info.available)
            self.assertIn("not found", info.detail)
        finally:
            compat.cli_present = original

    async def test_to_dict_shape(self):
        runner, _ = make_runner()
        payload = (await compat.probe_version(runner=runner)).to_dict()
        for key in ("available", "version", "cli_path", "detail"):
            self.assertIn(key, payload)


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(compat.parse_version("openshell 1.2.3"), "1.2.3")
        self.assertEqual(compat.parse_version("v0.9 build 42"), "0.9")
        self.assertEqual(compat.parse_version("no numbers"), "")

    def test_minimum_version_gate(self):
        self.assertTrue(compat.minimum_version_met("0.4.2", "0.1.0"))
        self.assertTrue(compat.minimum_version_met("1.0.0", "1.0.0"))
        self.assertFalse(compat.minimum_version_met("0.0.9", "0.1.0"))
        self.assertTrue(compat.minimum_version_met("", "0.0.0"))
        self.assertTrue(compat.minimum_version_met("0.10", "0.9"))


if __name__ == "__main__":
    unittest.main()
