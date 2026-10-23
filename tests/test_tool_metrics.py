import unittest

from kernel.bus import EventBus
from kernel.errors import ToolFailure
from kernel.metrics import REGISTRY
from tools.registry import Tool, ToolContext, ToolRegistry


class ToolMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_records_latency_and_counter(self):
        registry = ToolRegistry(EventBus())
        baseline = REGISTRY.counter("tool_metrics_quick_total")

        async def quick(ctx):
            return "ok"

        registry.register(Tool(name="metrics_quick", description="d",
                               parameters={}, handler=quick))
        await registry.call("metrics_quick", {}, ToolContext(source="agent"))
        self.assertEqual(REGISTRY.counter("tool_metrics_quick_total"),
                         baseline + 1)
        self.assertGreaterEqual(REGISTRY.histogram("tool_seconds")["count"], 1)

    async def test_error_paths_counted(self):
        registry = ToolRegistry(EventBus())

        async def fails(ctx):
            raise ToolFailure("nope")

        async def crashes(ctx):
            raise RuntimeError("boom")

        registry.register(Tool(name="metrics_fails", description="d",
                               parameters={}, handler=fails))
        registry.register(Tool(name="metrics_crashes", description="d",
                               parameters={}, handler=crashes))
        errors_before = REGISTRY.counter("tool_metrics_fails_errors_total")
        crashes_before = REGISTRY.counter("tool_metrics_crashes_crashes_total")
        try:
            await registry.call("metrics_fails", {},
                                ToolContext(source="agent"))
        except ToolFailure:
            pass
        try:
            await registry.call("metrics_crashes", {},
                                ToolContext(source="agent"))
        except ToolFailure:
            pass
        self.assertEqual(REGISTRY.counter("tool_metrics_fails_errors_total"),
                         errors_before + 1)
        self.assertEqual(
            REGISTRY.counter("tool_metrics_crashes_crashes_total"),
            crashes_before + 1)


if __name__ == "__main__":
    unittest.main()
