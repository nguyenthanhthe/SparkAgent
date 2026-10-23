"""Approvals workflow demo — the operator gate, end to end.

Shows how a risky agent action becomes a pending approval, how it
expires, and how an operator decision lands — fully offline:

    python examples/approvals_workflow.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.clock import FakeClock                        # noqa: E402
from kernel.errors import ApprovalRequired                # noqa: E402
from security.approval import (APPROVED, EXPIRED, PENDING,  # noqa: E402
                               ApprovalQueue)


def main() -> None:
    clock = FakeClock()
    queue = ApprovalQueue(ttl_seconds=120, clock=clock,
                          on_change=lambda request: print(
                              f"  [notify] {request.kind}: "
                              f"{request.status}"))

    print("1. agent wants to run a risky skill:")
    error = queue.require_approval("skill", "disk_cleaner_tool",
                                   {"dangerous": True})
    print("   raised:", type(error).__name__, "-", str(error)[:60])
    pending = queue.pending()
    print("   queue:", pending[0].kind, "-", pending[0].summary,
          f"({pending[0].status})")

    print("2. operator approves via dashboard/telegram/CLI:")
    decided = queue.approve(error.approval_id, decided_by="alice")
    print("   status:", decided.status, "by", decided.decided_by)

    print("3. a second request nobody reviews expires:")
    request = queue.submit("spend", "raise API budget to $50")
    clock.advance(121)
    print("   after TTL:", queue.get(request.id).status)
    try:
        queue.approve(request.id)
    except ValueError as exc:
        print("   late decision rejected:", str(exc)[:60])

    print("4. operator denies a third request:")
    third = queue.submit("command", "git push --force origin main")
    queue.deny(third.id, decided_by="bob")
    print("   status:", queue.get(third.id).status)

    print("\nrecent decisions:")
    for item in queue.recent():
        print(f"  {item.id[:8]} [{item.kind}] {item.status:<9} "
              f"{item.summary[:40]}")


if __name__ == "__main__":
    main()
