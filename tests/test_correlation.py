import asyncio
import unittest

from kernel.correlation import (TraceLog, current_span, current_trace_id,
                                new_id, trace)


class IdTests(unittest.TestCase):
    def test_ids_unique_and_shaped(self):
        ids = {new_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)
        for value in ids:
            self.assertEqual(len(value), 12)
            self.assertTrue(value.isalnum())
            self.assertTrue(value.islower() or value.isdigit())


class TraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_trace_creates_trace_id(self):
        with trace("episode") as span:
            self.assertEqual(span.parent_id, None)
            self.assertEqual(current_span(), span)
            self.assertEqual(current_trace_id(), span.trace_id)
        self.assertIsNotNone(span.duration_s)

    async def test_nested_span_shares_trace(self):
        with trace("episode") as root:
            with trace("tool:web_fetch") as child:
                self.assertEqual(child.trace_id, root.trace_id)
                self.assertEqual(child.parent_id, root.span_id)
            # after inner exit, current span is the root again
            self.assertEqual(current_span().span_id, root.span_id)

    async def test_sibling_traces_isolated(self):
        with trace("a") as a_span:
            pass
        with trace("b") as b_span:
            pass
        self.assertNotEqual(a_span.trace_id, b_span.trace_id)

    async def test_context_survives_await(self):
        with trace("outer") as span:
            await asyncio.sleep(0)
            self.assertEqual(current_trace_id(), span.trace_id)

    async def test_context_isolated_across_tasks(self):
        seen = {}

        async def worker(name):
            with trace(name) as span:
                await asyncio.sleep(0.01)
                seen[name] = current_trace_id() == span.trace_id

        await asyncio.gather(worker("t1"), worker("t2"))
        self.assertTrue(all(seen.values()))

    async def test_explicit_trace_id_propagates(self):
        with trace("parent", trace_id="fixed-trace") as parent:
            with trace("child") as child:
                self.assertEqual(child.trace_id, "fixed-trace")
        self.assertEqual(parent.trace_id, "fixed-trace")


class TraceLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_and_summarizes(self):
        log = TraceLog()
        with trace("alpha") as a:
            a.attributes["tool"] = "web_fetch"
        log.record(a)
        with trace("beta") as b:
            pass
        log.record(b)
        summary = log.summary()
        self.assertEqual(summary["span_count"], 2)
        self.assertEqual(summary["by_name"], {"alpha": 1, "beta": 1})
        self.assertGreaterEqual(summary["recorded_seconds"], 0.0)

    async def test_bounded_memory(self):
        log = TraceLog(max_spans=5)
        for _ in range(20):
            with trace("tick") as span:
                pass
            log.record(span)
        self.assertEqual(len(log.spans), 5)


if __name__ == "__main__":
    unittest.main()
