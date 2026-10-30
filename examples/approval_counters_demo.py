"""Approval counters demo: the queue lifecycle, offline.

A request is submitted, approved; another expires past its TTL and
carries the ``ttl`` reason (ADR-0011); ``counters_snapshot()`` reports
the whole lifecycle in one copy-safe dict.

    python examples/approval_counters_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.clock import FakeClock   # noqa: E402
from security.approval import ApprovalQueue   # noqa: E402


def main() -> None:
    clock = FakeClock()
    queue = ApprovalQueue(ttl_seconds=60, clock=clock)

    approved = queue.submit("skill", "word_counter tool", ttl=3600)
    queue.submit("spend", "$50 API budget", ttl=60)   # will expire
    print(f"submitted: {queue.counters_snapshot()['submitted']}")

    queue.approve(approved.id, decided_by="alice")
    snap = queue.counters_snapshot()
    print(f"approved : {snap['approved']}, pending_now={snap['pending_now']}")

    clock.advance(61)                        # past the spend request's TTL
    snap = queue.counters_snapshot()         # lazily expires
    expired = [r for r in queue.recent()
               if r.status == "expired"][0]
    print(f"expired  : {snap['expired']} "
          f"(expire_reason={expired.expire_reason!r}), "
          f"pending_now={snap['pending_now']}")


if __name__ == "__main__":
    main()
