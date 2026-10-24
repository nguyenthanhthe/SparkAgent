import json
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor
from tools.file_ops import register_tools
from tools.registry import ToolContext, ToolRegistry


def make_setup():
    sandbox = Path(tempfile.mkdtemp())
    policy = SecurityPolicy(["python"], [sandbox], sandbox)
    executor = SafeExecutor(policy, SecretVault(), EventBus(), timeout=15)
    registry = ToolRegistry()
    register_tools(registry, executor)
    return registry, sandbox


class FileOpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_and_read_roundtrip(self):
        registry, sandbox = make_setup()
        ctx = ToolContext(executor=None)
        written = json.loads(await registry.call("file_ops", {
            "operation": "write", "path": "notes/hello.txt",
            "content": "héllo sandbox"}, ctx))
        self.assertEqual(written["bytes_written"], 14)

        read = json.loads(await registry.call("file_ops", {
            "operation": "read", "path": "notes/hello.txt"}, ctx))
        self.assertEqual(read["content"], "héllo sandbox")
        self.assertFalse(read["truncated"])

    async def test_list_entries_sorted_dirs_first(self):
        registry, sandbox = make_setup()
        ctx = ToolContext()
        (sandbox / "zdir").mkdir()
        (sandbox / "afile.txt").write_text("x")
        (sandbox / "bdir").mkdir()
        result = json.loads(await registry.call("file_ops", {
            "operation": "list", "path": "."}, ctx))
        names = [e["name"] for e in result["entries"]]
        self.assertEqual(names, ["bdir", "zdir", "afile.txt"])
        types = {e["name"]: e["type"] for e in result["entries"]}
        self.assertEqual(types["bdir"], "dir")
        self.assertEqual(types["afile.txt"], "file")

    async def test_stat_reports_missing(self):
        registry, _ = make_setup()
        result = json.loads(await registry.call("file_ops", {
            "operation": "stat", "path": "nope.bin"}, ToolContext()))
        self.assertFalse(result["exists"])

    async def test_stat_reports_file(self):
        registry, sandbox = make_setup()
        (sandbox / "f.txt").write_text("12345")
        result = json.loads(await registry.call("file_ops", {
            "operation": "stat", "path": "f.txt"}, ToolContext()))
        self.assertTrue(result["exists"])
        self.assertEqual(result["size"], 5)
        self.assertEqual(result["type"], "file")

    async def test_escape_attempt_rejected(self):
        registry, _ = make_setup()
        with self.assertRaises(Exception) as caught:
            await registry.call("file_ops", {
                "operation": "read", "path": "../outside.txt"}, ToolContext())
        self.assertIn("allowed roots", str(caught.exception))

    async def test_read_missing_file_is_tool_error(self):
        registry, _ = make_setup()
        with self.assertRaises(Exception) as caught:
            await registry.call("file_ops", {
                "operation": "read", "path": "ghost.txt"}, ToolContext())
        self.assertIn("not a file", str(caught.exception))

    async def test_truncation_flag_on_large_file(self):
        registry, sandbox = make_setup()
        (sandbox / "big.txt").write_text("x" * 70_000)
        # call the handler directly: registry.call truncates oversized
        # JSON results, which would mangle the payload under test
        handler = registry.get("file_ops").handler
        result = await handler(ToolContext(), operation="read",
                               path="big.txt", content="")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["content"]), 65_536)


if __name__ == "__main__":
    unittest.main()
