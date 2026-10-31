import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.errors import ToolFailure
from kernel.memory import Memory
from kernel.clock import FakeClock
from security.approval import ApprovalQueue, PENDING
from tools.registry import ToolContext, ToolRegistry
from tools.stdlib_tools import register_tools


def make_registry(approvals=None):
    registry = ToolRegistry(EventBus())
    register_tools(registry, approvals)
    ctx = ToolContext(source="agent")
    return registry, ctx


async def make_registry_with_memory():
    registry = ToolRegistry(EventBus())
    register_tools(registry, None)
    memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=128)
    await memory.connect()
    return registry, ToolContext(source="agent", memory=memory), memory


class RegisteredToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry, self.ctx = make_registry()

    async def test_all_tools_registered(self):
        expected = {"calculate", "text_analysis", "json_query",
                    "csv_analyze", "statistics", "remember",
                    "recall_memory", "ask_human"}
        self.assertTrue(expected.issubset(set(self.registry.names())))

    async def test_calculate(self):
        result = await self.registry.call(
            "calculate", {"expression": "sqrt(144) + 2**5"}, self.ctx)
        self.assertIn("44", result)

    async def test_calculate_errors_returned_structurally(self):
        # calculator reports failures as data the model can read, not raises
        result = await self.registry.call(
            "calculate", {"expression": "1/0"}, self.ctx)
        self.assertIn('"ok": false', result)
        self.assertIn("division by zero", result)
        result = await self.registry.call(
            "calculate", {"expression": "__import__('os')"}, self.ctx)
        self.assertIn("not allowed", result)

    async def test_text_analysis_words(self):
        result = await self.registry.call(
            "text_analysis", {"text": "cat dog cat bird cat",
                              "operation": "words"}, self.ctx)
        self.assertIn("cat", result)

    async def test_text_analysis_bad_operation(self):
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "text_analysis", {"text": "x", "operation": "nope"},
                self.ctx)

    async def test_json_query_get_and_bad_json(self):
        result = await self.registry.call(
            "json_query", {"data": '{"a": {"b": 7}}', "path": "a.b",
                           "mode": "get"}, self.ctx)
        self.assertIn("7", result)
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": "{not json", "mode": "shape"},
                self.ctx)

    async def test_json_query_shape_honors_max_depth(self):
        deep = '{"a": {"b": {"c": {"d": {"e": 1}}}}}'
        # default depth 4 truncates at level 4
        default = await self.registry.call(
            "json_query", {"data": deep, "mode": "shape"}, self.ctx)
        self.assertIn("…", default)
        # caller raises the limit and level e becomes visible
        deep_result = await self.registry.call(
            "json_query", {"data": deep, "mode": "shape", "max_depth": 6},
            self.ctx)
        self.assertIn("int", deep_result)
        # caller clamps down to a single level
        shallow = await self.registry.call(
            "json_query", {"data": deep, "mode": "shape", "max_depth": 1},
            self.ctx)
        self.assertEqual(shallow.strip(), '{"shape": {"a": "…"}}')

    async def test_json_query_jsonl_mode(self):
        jsonl = '{"name": "alice", "n": 1}\n\n{"name": "bob", "n": 2}\n'
        result = await self.registry.call(
            "json_query", {"data": jsonl, "mode": "get",
                           "path": "1.name", "jsonl": True}, self.ctx)
        self.assertIn("bob", result)
        result = await self.registry.call(
            "json_query", {"data": jsonl, "mode": "stats", "jsonl": True},
            self.ctx)
        self.assertIn('"list_len": 2', result)

    async def test_json_query_jsonl_bad_line_reports_number(self):
        with self.assertRaises(ToolFailure) as caught:
            await self.registry.call(
                "json_query", {"data": '{"ok": 1}\n{broken\n',
                               "mode": "stats", "jsonl": True}, self.ctx)
        self.assertIn("line 2", str(caught.exception))

    async def test_csv_analyze_filter(self):
        csv_data = "name,score\nalice,90\nbob,70\n"
        result = await self.registry.call(
            "csv_analyze", {"data": csv_data, "operation": "filter",
                            "column": "score", "op": ">", "value": "80"},
            self.ctx)
        self.assertIn("alice", result)
        self.assertNotIn("bob", result)

    async def test_statistics_summary(self):
        result = await self.registry.call(
            "statistics", {"values": "1 2 3 4 5",
                           "operation": "summary"}, self.ctx)
        self.assertIn("mean", result)
        self.assertIn("3", result)

    async def test_statistics_regression(self):
        result = await self.registry.call(
            "statistics", {"values": "0 1 2 3", "values2": "1 3 5 7",
                           "operation": "regression"}, self.ctx)
        self.assertIn("slope", result)

    async def test_json_query_search_toggles(self):
        import json as json_lib
        data = '{"hostname": "gpu-01", "note": "hostname alias"}'
        both = json_lib.loads(await self.registry.call(
            "json_query", {"data": data, "mode": "search",
                           "path": "hostname"}, self.ctx))
        self.assertIn("hostname", both["matches"])
        self.assertEqual(both["count"], 2)   # key + the alias value
        # values-only: the key match disappears, the value match stays
        values_only = json_lib.loads(await self.registry.call(
            "json_query", {"data": data, "mode": "search",
                           "path": "hostname", "in_keys": False},
            self.ctx))
        self.assertEqual(values_only["matches"], ["note"])
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": data, "mode": "search",
                               "path": "x", "in_keys": False,
                               "in_values": False}, self.ctx)

    async def test_csv_filter_reports_counts(self):
        import json as json_lib
        csv_text = "name,status\nalice,active\nbob,done\ncara,active\n"
        result = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": csv_text, "operation": "filter",
                            "column": "status", "op": "==",
                            "value": "active"}, self.ctx))
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["total"], 3)

    async def test_csv_head_negative_limit_clamps_to_one(self):
        import json as json_lib
        result = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": "n\n1\n2\n", "operation": "head",
                            "limit": -5}, self.ctx))
        self.assertEqual(len(result["rows"]), 1)   # clamped, no crash
        over = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": "n\n1\n2\n", "operation": "head",
                            "limit": 5000}, self.ctx))
        self.assertEqual(len(over["rows"]), 2)     # capped at the data

    async def test_json_query_get_default_on_miss(self):
        import json as json_lib
        # a miss without a default still fails
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": '{"a": 1}', "path": "b",
                               "mode": "get"}, self.ctx)
        result = json_lib.loads(await self.registry.call(
            "json_query", {"data": '{"a": 1}', "path": "b", "mode": "get",
                           "default_json": "42"}, self.ctx))
        self.assertEqual(result["value"], 42)
        self.assertTrue(result["default_used"])
        # a hit ignores the default
        hit = json_lib.loads(await self.registry.call(
            "json_query", {"data": '{"a": 1}', "path": "a", "mode": "get",
                           "default_json": "42"}, self.ctx))
        self.assertEqual(hit["value"], 1)
        self.assertNotIn("default_used", hit)
        # an unparsable default degrades to the normal failure
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": '{"a": 1}', "path": "b",
                               "mode": "get", "default_json": "{nope"},
                self.ctx)

    async def test_csv_head_honors_limit(self):
        import json as json_lib
        csv_text = "n\n" + "".join(f"{i}\n" for i in range(40))
        default = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": csv_text, "operation": "head"},
            self.ctx))
        self.assertEqual(len(default["rows"]), 25)
        custom = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": csv_text, "operation": "head",
                            "limit": 3}, self.ctx))
        self.assertEqual(len(custom["rows"]), 3)
        # limit also truncates filter/sort output
        filtered = json_lib.loads(await self.registry.call(
            "csv_analyze", {"data": csv_text, "operation": "filter",
                            "column": "n", "op": ">=", "value": "0",
                            "limit": 2}, self.ctx))
        self.assertEqual(len(filtered["rows"]), 2)


class MemoryToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_remember_and_recall_via_tools(self):
        self.registry, self.ctx, memory = await make_registry_with_memory()
        stored = await self.registry.call(
            "remember", {"text": "gpu temperature threshold is 85c",
                         "kind": "fact"}, self.ctx)
        self.assertIn("stored", stored)
        recalled = await self.registry.call(
            "recall_memory", {"query": "gpu temperature"}, self.ctx)
        self.assertIn("gpu", recalled)
        await memory.close()

    async def test_memory_tools_fail_cleanly_without_memory(self):
        registry, ctx = make_registry()
        with self.assertRaises(ToolFailure):
            await registry.call("remember", {"text": "x"}, ctx)


class AskHumanTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_pending_approval(self):
        queue = ApprovalQueue(clock=FakeClock())
        registry, ctx = make_registry(approvals=queue)
        result = await registry.call(
            "ask_human", {"question": "Should I delete the old backups?"},
            ctx)
        self.assertIn("operator", result)
        pending = queue.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, PENDING)
        self.assertIn("backups", pending[0].summary)

    async def test_disabled_approvals_clear_error(self):
        registry, ctx = make_registry(approvals=None)
        with self.assertRaises(ToolFailure) as ctx_err:
            await registry.call("ask_human", {"question": "hi?"}, ctx)
        self.assertIn("disabled", str(ctx_err.exception))


if __name__ == "__main__":
    unittest.main()
