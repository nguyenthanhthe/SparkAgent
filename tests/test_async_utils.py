import asyncio
import unittest

from kernel.async_utils import Debouncer, TaskGroup, gather_limit, timeout_box


class GatherLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_order(self):
        async def val(x):
            await asyncio.sleep(0.01 * (5 - x))
            return x
        result = await gather_limit([val(i) for i in range(5)], limit=2)
        self.assertEqual(result, [0, 1, 2, 3, 4])

    async def test_respects_concurrency_cap(self):
        running = peak = 0

        async def work():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

        await gather_limit([work() for _ in range(6)], limit=2)
        self.assertLessEqual(peak, 2)

    async def test_propagates_exceptions(self):
        async def boom():
            raise ValueError("x")
        with self.assertRaises(ValueError):
            await gather_limit([boom()], limit=1)


class TimeoutBoxTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_result(self):
        async def quick():
            return 42
        self.assertEqual(await timeout_box(quick(), 1.0), 42)

    async def test_times_out_and_cancels(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def slow():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(asyncio.TimeoutError):
            await timeout_box(slow(), 0.05)
        self.assertTrue(started.is_set())
        self.assertTrue(cancelled.is_set())


class TaskGroupTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_collects_results_and_exceptions(self):
        async def good():
            return "ok"

        async def bad():
            raise RuntimeError("nope")

        async with TaskGroup() as group:
            group.run(good())
            group.run(bad())
        results = await group.wait() if not group.tasks else group.tasks
        # after __aexit__ the tasks are done; inspect their outcomes
        outcomes = [t.exception() if t.exception() else t.result()
                    for t in group.tasks]
        self.assertIn("ok", outcomes)
        self.assertTrue(any(isinstance(o, RuntimeError) for o in outcomes))

    async def test_cancel_all(self):
        entered = asyncio.Event()

        async def forever():
            entered.set()
            await asyncio.sleep(60)

        group = TaskGroup()
        group.run(forever())
        await entered.wait()
        self.assertEqual(group.cancel_all(), 1)
        outcomes = await group.wait()
        self.assertTrue(all(isinstance(o, asyncio.CancelledError)
                            for o in outcomes))


class DebouncerTests(unittest.IsolatedAsyncioTestCase):
    async def test_coalesces_bursts(self):
        fired = []

        async def sink(value):
            fired.append(value)

        deb = Debouncer(delay=0.02, fn=sink)
        for i in range(10):
            deb.call(i)
            await asyncio.sleep(0.002)
        await asyncio.sleep(0.08)
        self.assertEqual(deb.calls, 10)
        self.assertEqual(deb.fired, 1)
        self.assertEqual(fired, [9])  # only the last value fires


class MaybeAwaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_value(self):
        from kernel.async_utils import maybe_await
        self.assertEqual(await maybe_await(7), 7)

    async def test_coroutine(self):
        from kernel.async_utils import maybe_await
        self.assertEqual(await maybe_await(_one()), 1)

    async def test_sync_callable(self):
        from kernel.async_utils import maybe_await
        self.assertEqual(await maybe_await(lambda: 3), 3)


async def _one():
    return 1


if __name__ == "__main__":
    unittest.main()
