import unittest

from kernel.clock import Clock, FakeClock
from kernel.config import Config
from kernel.daemon import AgentDaemon
from security.approval import EXPIRED, PENDING, ApprovalQueue


class ApprovalSweepTests(unittest.IsolatedAsyncioTestCase):
    async def test_sweep_expires_overdue(self):
        clock = FakeClock()
        daemon = AgentDaemon(Config.load())
        # swap in a fake-clock queue for deterministic expiry
        daemon.approvals = ApprovalQueue(ttl_seconds=10, clock=clock)
        request = daemon.approvals.submit("skill", "old_request")
        clock.advance(11)
        self.assertEqual(daemon.approvals.get(request.id).status, EXPIRED)

    async def test_sweep_keeps_fresh_pending(self):
        clock = FakeClock()
        daemon = AgentDaemon(Config.load())
        daemon.approvals = ApprovalQueue(ttl_seconds=600, clock=clock)
        request = daemon.approvals.submit("skill", "fresh_request")
        daemon.approvals.pending()
        self.assertEqual(daemon.approvals.get(request.id).status, PENDING)

    async def test_sweep_count_method(self):
        clock = FakeClock()
        daemon = AgentDaemon(Config.load())
        daemon.approvals = ApprovalQueue(ttl_seconds=10, clock=clock)
        daemon.approvals.submit("generic", "will expire")
        clock.advance(11)
        expired = daemon._sweep_expired_approvals()
        self.assertEqual(expired, 1)
        # second sweep finds nothing new
        self.assertEqual(daemon._sweep_expired_approvals(), 0)

    async def test_default_queue_uses_real_clock(self):
        daemon = AgentDaemon(Config.load())
        self.assertIsInstance(daemon.approvals.clock, Clock)


if __name__ == "__main__":
    unittest.main()
