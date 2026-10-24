import unittest

from security.auth_limiter import AuthRateLimiter


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class AuthRateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.limiter = AuthRateLimiter(max_failures=3, window_seconds=60,
                                       lockout_seconds=120,
                                       clock=self.clock)

    def test_allows_below_threshold(self):
        for _ in range(2):
            self.limiter.record_failure("1.2.3.4")
        self.assertTrue(self.limiter.allowed("1.2.3.4"))

    def test_locks_at_threshold(self):
        for _ in range(3):
            self.limiter.record_failure("1.2.3.4")
        self.assertFalse(self.limiter.allowed("1.2.3.4"))
        self.assertEqual(self.limiter.retry_after("1.2.3.4"), 120.0)

    def test_lockout_expires(self):
        for _ in range(3):
            self.limiter.record_failure("1.2.3.4")
        self.clock.t += 121
        self.assertTrue(self.limiter.allowed("1.2.3.4"))

    def test_window_forgets_old_failures(self):
        self.limiter.record_failure("1.2.3.4")
        self.clock.t += 61
        self.limiter.record_failure("1.2.3.4")
        self.clock.t += 61
        self.limiter.record_failure("1.2.3.4")
        self.assertTrue(self.limiter.allowed("1.2.3.4"))

    def test_success_clears_failures(self):
        self.limiter.record_failure("1.2.3.4")
        self.limiter.record_failure("1.2.3.4")
        self.limiter.record_success("1.2.3.4")
        self.limiter.record_failure("1.2.3.4")
        self.assertTrue(self.limiter.allowed("1.2.3.4"))

    def test_clients_independent(self):
        for _ in range(3):
            self.limiter.record_failure("1.2.3.4")
        self.assertTrue(self.limiter.allowed("5.6.7.8"))

    def test_failures_during_lockout_do_not_extend(self):
        for _ in range(3):
            self.limiter.record_failure("1.2.3.4")
        self.clock.t += 60
        self.limiter.record_failure("1.2.3.4")   # ignored: still locked out
        self.assertEqual(self.limiter.retry_after("1.2.3.4"), 60.0)

    def test_snapshot_counts_locked(self):
        for _ in range(3):
            self.limiter.record_failure("1.2.3.4")
        snap = self.limiter.snapshot()
        self.assertEqual(snap["locked_now"], 1)
        self.assertEqual(snap["lockouts_issued"], 1)


if __name__ == "__main__":
    unittest.main()
