import asyncio
import unittest

from kernel.clock import Clock, Deadline, FakeClock, Stopwatch, human_duration
from kernel.errors import RateLimitedError
from kernel.limits import ConcurrencyGuard, RateLimiterSet, TokenBucket


class ClockTests(unittest.TestCase):
    def test_fake_clock_advances_both_times(self):
        clock = FakeClock()
        start = clock.now()
        clock.advance(5)
        self.assertEqual(clock.now(), start + 5)
        self.assertEqual(clock.monotonic(), 5)

    async def _fake_sleep_yields_without_waiting(self):
        clock = FakeClock()
        import time
        before = time.monotonic()
        await clock.sleep(60)
        return time.monotonic() - before, clock.now()

    def test_fake_sleep_does_not_block(self):
        elapsed, wall = asyncio.run(self._fake_sleep_yields_without_waiting())
        self.assertLess(elapsed, 0.5)
        self.assertEqual(wall, 1_000_060.0)

    def test_stopwatch_laps(self):
        clock = FakeClock()
        watch = Stopwatch(clock)
        clock.advance(1)
        watch.lap("first")
        clock.advance(2)
        report = watch.report()
        self.assertEqual(report["first"], 1.0)
        self.assertEqual(report["total_s"], 3.0)

    def test_human_duration(self):
        self.assertEqual(human_duration(0.0005), "500us")
        self.assertEqual(human_duration(0.02), "20ms")
        self.assertEqual(human_duration(45), "45.0s")
        self.assertEqual(human_duration(62), "1m02s")
        self.assertEqual(human_duration(3661), "1h01m")
        self.assertEqual(human_duration(90061), "1d01h")

    def test_deadline(self):
        clock = FakeClock()
        deadline = Deadline(10, clock)
        self.assertFalse(deadline.expired)
        clock.advance(11)
        self.assertTrue(deadline.expired)
        self.assertEqual(deadline.remaining, 0.0)


class TokenBucketTests(unittest.TestCase):
    def test_burst_then_refill(self):
        clock = FakeClock()
        bucket = TokenBucket(capacity=3, refill_per_second=1.0, clock=clock)
        self.assertTrue(bucket.try_take(3))       # full burst
        self.assertFalse(bucket.try_take(1))      # empty
        clock.advance(1.0)
        self.assertTrue(bucket.try_take(1))       # refilled 1 token

    def test_capacity_caps_refill(self):
        clock = FakeClock()
        bucket = TokenBucket(capacity=2, refill_per_second=10, clock=clock)
        clock.advance(100)
        self.assertTrue(bucket.try_take(2))
        self.assertFalse(bucket.try_take(1))      # capped at 2, not 1000

    def test_take_raises_with_retry_after(self):
        clock = FakeClock()
        bucket = TokenBucket(capacity=1, refill_per_second=2.0, clock=clock)
        self.assertEqual(bucket.take(1), 0.0)
        with self.assertRaises(RateLimitedError) as ctx:
            bucket.take(1)
        self.assertAlmostEqual(ctx.exception.retry_after, 0.5, places=3)

    def test_concurrent_takes_thread_safe(self):
        bucket = TokenBucket(capacity=100, refill_per_second=1)
        import threading
        taken = []
        lock = threading.Lock()

        def worker():
            for _ in range(50):
                ok = bucket.try_take()
                with lock:
                    taken.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(taken), 100)

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            TokenBucket(capacity=0, refill_per_second=1)


class RateLimiterSetTests(unittest.TestCase):
    def test_isolated_named_buckets(self):
        clock = FakeClock()
        limiter = RateLimiterSet(capacity=2, refill_per_second=1, clock=clock)
        self.assertTrue(limiter.try_take("web", 2))
        self.assertFalse(limiter.try_take("web"))
        self.assertTrue(limiter.try_take("llm", 2))  # independent bucket


class ConcurrencyGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_caps_inflight(self):
        guard = ConcurrencyGuard(limit=2)
        running = peak = 0

        async def work():
            nonlocal running, peak
            async with guard:
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.02)
                running -= 1

        await asyncio.gather(*(work() for _ in range(6)))
        self.assertLessEqual(peak, 2)
        self.assertEqual(guard.stats["peak"], 2)
        self.assertEqual(guard.stats["active"], 0)


if __name__ == "__main__":
    unittest.main()
