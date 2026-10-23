import unittest

from kernel.clock import FakeClock
from kernel.circuit import CircuitBreaker, CircuitOpenError, State
from kernel.errors import RateLimitedError, SparkError, ToolFailure
from kernel.retry import RetryPolicy, RetryBudget, call_with_retry


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_succeeds_first_try(self):
        calls = []

        async def ok():
            calls.append(1)
            return "value"

        result = await call_with_retry(ok)
        self.assertEqual(result, "value")
        self.assertEqual(len(calls), 1)

    async def test_retries_then_succeeds(self):
        attempts = []

        async def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")
            return "recovered"

        result = await call_with_retry(flaky, policy=RetryPolicy(
            attempts=5, base_delay=0.001, jitter=False))
        self.assertEqual(result, "recovered")
        self.assertEqual(len(attempts), 3)

    async def test_exhaustion_raises_last(self):
        async def always_fails():
            raise ValueError("broken")

        with self.assertRaises(ValueError):
            await call_with_retry(always_fails, policy=RetryPolicy(
                attempts=3, base_delay=0.001, jitter=False))

    async def test_non_retryable_spark_error_aborts(self):
        calls = []

        async def bad():
            calls.append(1)
            raise ToolFailure("bad input")

        with self.assertRaises(ToolFailure):
            await call_with_retry(bad, policy=RetryPolicy(attempts=5))
        self.assertEqual(len(calls), 1)  # no retries burned

    async def test_retry_after_respected(self):
        clock = FakeClock()
        waited = []

        async def sleep(seconds):
            waited.append(seconds)
            await clock.sleep(seconds)

        attempts = []

        async def limited():
            attempts.append(1)
            if len(attempts) < 2:
                raise RateLimitedError("quota", retry_after=0.75)
            return "ok"

        result = await call_with_retry(
            limited, policy=RetryPolicy(attempts=3, base_delay=0.01,
                                        jitter=False),
            sleep=sleep)
        self.assertEqual(result, "ok")
        self.assertGreaterEqual(waited[0], 0.75)

    async def test_backoff_growth(self):
        policy = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=50,
                             jitter=False)
        self.assertEqual(policy.delay_for(0), 1.0)
        self.assertEqual(policy.delay_for(1), 2.0)
        self.assertEqual(policy.delay_for(4), 16.0)
        self.assertEqual(policy.delay_for(10), 50.0)  # capped

    async def test_jitter_stays_in_range(self):
        policy = RetryPolicy(base_delay=1.0, multiplier=1.0, jitter=True)
        for _ in range(50):
            delay = policy.delay_for(0)
            self.assertGreaterEqual(delay, 0.5)
            self.assertLessEqual(delay, 1.0)


class RetryBudgetTests(unittest.TestCase):
    def test_tracks_retries_and_exhaustion(self):
        budget = RetryBudget()
        budget.record("tool:fetch", success=True, attempts=3)
        budget.record("tool:fetch", success=False, attempts=5)
        snap = budget.snapshot()["tool:fetch"]
        self.assertEqual(snap["calls"], 2)
        self.assertEqual(snap["retries"], 6)
        self.assertEqual(snap["exhausted"], 1)


class CircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    def make(self, **kw):
        defaults = dict(name="test", failure_threshold=3, reset_timeout=10,
                        clock=FakeClock())
        defaults.update(kw)
        return CircuitBreaker(**defaults)

    async def test_opens_after_threshold(self):
        breaker = self.make()

        async def fail():
            raise RuntimeError("down")

        for i in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(fail)
        self.assertEqual(breaker.state, State.OPEN)
        with self.assertRaises(CircuitOpenError):
            await breaker.call(fail)
        self.assertEqual(breaker.metrics["rejected"], 1)

    async def test_successes_reset_failures(self):
        breaker = self.make()

        async def ok():
            return 1

        async def fail():
            raise RuntimeError("down")

        with self.assertRaises(RuntimeError):
            await breaker.call(fail)
        with self.assertRaises(RuntimeError):
            await breaker.call(fail)
        await breaker.call(ok)   # resets failure count
        with self.assertRaises(RuntimeError):
            await breaker.call(fail)
        self.assertEqual(breaker.state, State.CLOSED)  # only 1 failure since

    async def test_half_open_recovers_after_timeout(self):
        breaker = self.make()
        clock = breaker.clock

        async def fail():
            raise RuntimeError("down")

        async def ok():
            return "back"

        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(fail)
        self.assertEqual(breaker.state, State.OPEN)

        clock.advance(10)  # reset timeout elapses
        self.assertEqual(breaker.state, State.HALF_OPEN)
        self.assertEqual(await breaker.call(ok), "back")   # win 1
        self.assertEqual(await breaker.call(ok), "back")   # win 2 -> closed
        self.assertEqual(breaker.state, State.CLOSED)

    async def test_half_open_failure_reopens(self):
        breaker = self.make()
        clock = breaker.clock

        async def fail():
            raise RuntimeError("down")

        async def ok():
            return 1

        for _ in range(3):
            with self.assertRaises(RuntimeError):
                await breaker.call(fail)
        clock.advance(10)
        await breaker.call(ok)          # half-open, one win
        with self.assertRaises(RuntimeError):
            await breaker.call(fail)    # trips again immediately
        self.assertEqual(breaker.state, State.OPEN)

    def test_circuit_open_error_is_retryable(self):
        err = CircuitOpenError("brain", 5.0)
        self.assertIsInstance(err, SparkError)
        self.assertTrue(err.retryable)
        self.assertEqual(err.remaining, 5.0)

    def test_snapshot_shape(self):
        breaker = self.make()
        snap = breaker.snapshot()
        self.assertEqual(snap["name"], "test")
        self.assertEqual(snap["state"], "closed")


if __name__ == "__main__":
    unittest.main()
