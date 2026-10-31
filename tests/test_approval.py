import unittest

from kernel.clock import FakeClock
from kernel.errors import ApprovalRequired
from security.approval import (APPROVED, DENIED, EXPIRED, PENDING,
                               ApprovalQueue, request_to_dict)


class ApprovalQueueTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.queue = ApprovalQueue(ttl_seconds=60, clock=self.clock)

    def test_submit_creates_pending(self):
        request = self.queue.submit("skill", "word_counter tool",
                                    {"code_lines": 8})
        self.assertEqual(request.status, PENDING)
        self.assertEqual(self.queue.pending()[0].id, request.id)

    def test_approve_flow(self):
        request = self.queue.submit("command", "git push")
        decided = self.queue.approve(request.id, decided_by="alice")
        self.assertEqual(decided.status, APPROVED)
        self.assertEqual(decided.decided_by, "alice")
        self.assertEqual(self.queue.pending(), [])

    def test_deny_flow(self):
        request = self.queue.submit("spend", "$50 API budget")
        self.queue.deny(request.id)
        self.assertEqual(self.queue.get(request.id).status, DENIED)

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            self.queue.approve("nope")

    def test_expiry_after_ttl(self):
        request = self.queue.submit("skill", "x")
        self.clock.advance(61)
        self.assertEqual(self.queue.get(request.id).status, EXPIRED)
        self.assertEqual(self.queue.pending(), [])

    def test_expiry_carries_ttl_reason(self):
        request = self.queue.submit("skill", "x")
        self.clock.advance(61)
        expired = self.queue.get(request.id)
        self.assertEqual(expired.expire_reason, "ttl")
        payload = request_to_dict(expired)
        self.assertEqual(payload["expire_reason"], "ttl")
        # decided paths never set the reason
        other = self.queue.submit("skill", "y")
        decided = self.queue.approve(other.id)
        self.assertIsNone(decided.expire_reason)

    def test_decided_payload_carries_decided_at(self):
        request = self.queue.submit("skill", "x")
        self.clock.advance(5)
        decided = self.queue.approve(request.id)
        payload = request_to_dict(decided)
        self.assertEqual(payload["decided_at"], 1000005.0)  # FakeClock base + 5s
        self.assertEqual(payload["decided_by"], "operator")
        # a pending request has neither decision field set
        pending = self.queue.submit("skill", "y")
        p_payload = request_to_dict(pending)
        self.assertIsNone(p_payload["decided_at"])
        # the deadline is visible so operators know when it dies
        # (submitted at 1000005 after the advance, ttl 60s)
        self.assertEqual(p_payload["expires_at"], 1000065.0)

    def test_decision_after_expiry_is_rejected(self):
        request = self.queue.submit("skill", "x")
        self.clock.advance(61)
        with self.assertRaises(ValueError) as ctx:
            self.queue.approve(request.id)
        self.assertIn("expired", str(ctx.exception))

    def test_counters_snapshot_shape(self):
        first = self.queue.submit("skill", "x")
        self.queue.submit("spend", "y")
        self.queue.approve(first.id)
        snap = self.queue.counters_snapshot()
        self.assertEqual(snap["submitted"], 2)
        self.assertEqual(snap["approved"], 1)
        self.assertEqual(snap["pending_now"], 1)
        # the snapshot is a copy — mutating it must not touch the queue
        snap["submitted"] = 99
        self.assertEqual(self.queue.counters["submitted"], 2)
        # expiry flows through the snapshot too
        self.clock.advance(61)
        snap = self.queue.counters_snapshot()
        self.assertEqual(snap["expired"], 1)
        self.assertEqual(snap["pending_now"], 0)

    def test_require_approval_error_carries_id(self):
        err = self.queue.require_approval("skill", "needs review")
        self.assertIsInstance(err, ApprovalRequired)
        self.assertIn(err.approval_id, self.queue._requests)

    def test_observer_notified(self):
        events = []
        queue = ApprovalQueue(clock=self.clock, on_change=events.append)
        queue.submit("skill", "x")
        self.assertEqual(len(events), 1)
        queue.approve(events[0].id)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].status, APPROVED)

    def test_observer_failure_isolated(self):
        def broken(_request):
            raise RuntimeError("observer bug")

        queue = ApprovalQueue(clock=self.clock, on_change=broken)
        request = queue.submit("skill", "x")  # must not raise
        self.assertEqual(request.status, PENDING)

    def test_recent_listing(self):
        for i in range(5):
            self.queue.submit("generic", f"item {i}")
        recent = self.queue.recent(limit=3)
        self.assertEqual(len(recent), 3)
        # newest first
        self.assertEqual(recent[0].summary, "item 4")

    def test_to_dict_roundtrip_shape(self):
        request = self.queue.submit("skill", "s", {"a": 1})
        payload = request_to_dict(request)
        self.assertEqual(payload["kind"], "skill")
        self.assertEqual(payload["detail"], {"a": 1})
        self.assertEqual(payload["status"], PENDING)


if __name__ == "__main__":
    unittest.main()
