"""Operator approval workflow for sensitive actions.

Anything that should not run without a human nod (new skills, destructive
commands, spend above a threshold) creates a :class:`Request`. Requests
live in memory with optional persistence callbacks; approval can expire so
a stale queue does not accumulate. Used by SkillForge (v2) and the
``ask_human`` tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kernel.clock import Clock
from kernel.correlation import new_id
from kernel.errors import ApprovalRequired

PENDING, APPROVED, DENIED, EXPIRED = "pending", "approved", "denied", "expired"


@dataclass
class Request:
    kind: str                      # skill | command | spend | generic
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    requested_by: str = "agent"
    id: str = field(default_factory=new_id)
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None
    status: str = PENDING
    decided_by: str | None = None
    decided_at: float | None = None
    # why the request left PENDING without a decision — "ttl" on expiry
    expire_reason: str | None = None


Observer = Callable[[Request], None]


class ApprovalQueue:
    def __init__(self, ttl_seconds: float = 3600.0, clock: Clock | None = None,
                 on_change: Observer | None = None):
        self.ttl = ttl_seconds
        self.clock = clock or Clock()
        self._requests: dict[str, Request] = {}
        self._observers: list[Observer] = ([on_change] if on_change else [])
        self.counters = {"submitted": 0, "approved": 0, "denied": 0,
                         "expired": 0}

    # ------------------------------------------------------------------ state
    def submit(self, kind: str, summary: str, detail: dict | None = None,
               requested_by: str = "agent", ttl: float | None = None) -> Request:
        request = Request(kind=kind, summary=summary[:500],
                          detail=detail or {}, requested_by=requested_by,
                          expires_at=self.clock.now() + (ttl or self.ttl))
        self._requests[request.id] = request
        self.counters["submitted"] += 1
        self._notify(request)
        return request

    def approve(self, request_id: str, decided_by: str = "operator") -> Request:
        return self._decide(request_id, APPROVED, decided_by)

    def deny(self, request_id: str, decided_by: str = "operator") -> Request:
        return self._decide(request_id, DENIED, decided_by)

    def _decide(self, request_id: str, status: str, decided_by: str) -> Request:
        request = self._get_fresh(request_id)
        if request.status != PENDING:
            raise ValueError(
                f"approval request {request_id!r} is already "
                f"{request.status}; only pending requests can be decided")
        request.status = status
        self.counters["approved" if status == APPROVED else "denied"] += 1
        request.decided_by = decided_by
        request.decided_at = self.clock.now()
        self._notify(request)
        return request

    def get(self, request_id: str) -> Request:
        return self._get_fresh(request_id)

    def _get_fresh(self, request_id: str) -> Request:
        request = self._requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown approval request {request_id!r}")
        if (request.status == PENDING and request.expires_at is not None
                and self.clock.now() > request.expires_at):
            request.status = EXPIRED
            request.expire_reason = "ttl"
            self.counters["expired"] += 1
            self._notify(request)
        return request

    # ---------------------------------------------------------------- listing
    def pending(self) -> list[Request]:
        self._expire_all()
        return [r for r in self._requests.values() if r.status == PENDING]

    def recent(self, limit: int = 50) -> list[Request]:
        self._expire_all()
        requests = sorted(self._requests.values(),
                          key=lambda r: r.created_at, reverse=True)
        return requests[:limit]

    def _expire_all(self) -> None:
        now = self.clock.now()
        for request in self._requests.values():
            if (request.status == PENDING and request.expires_at is not None
                    and now > request.expires_at):
                request.status = EXPIRED
                request.expire_reason = "ttl"
                self.counters["expired"] += 1
                self._notify(request)

    def counters_snapshot(self) -> dict:
        """The lifecycle counters plus the live queue depth, the TTL
        the queue enforces, and the registered observer count — a copy,
        so callers cannot mutate the queue's bookkeeping."""
        self._expire_all()
        return {**self.counters,
                "pending_now": len(self.pending()),
                "ttl_seconds": self.ttl,
                "observers": len(self._observers)}

    # --------------------------------------------------------------- helpers
    def require_approval(self, kind: str, summary: str,
                         detail: dict | None = None) -> ApprovalRequired:
        """Submit and return the error to raise (agent-side convenience)."""
        request = self.submit(kind, summary, detail)
        return ApprovalRequired(
            f"{kind} requires operator approval: {summary}", request.id)

    def observe(self, observer: Observer) -> None:
        self._observers.append(observer)

    def _notify(self, request: Request) -> None:
        for observer in self._observers:
            try:
                observer(request)
            except Exception:  # noqa: BLE001 — observers must not break the queue
                pass


def request_to_dict(request: Request) -> dict:
    return {"id": request.id, "kind": request.kind, "summary": request.summary,
            "detail": request.detail, "requested_by": request.requested_by,
            "status": request.status, "created_at": request.created_at,
            "expires_at": request.expires_at,
            "decided_by": request.decided_by,
            "decided_at": request.decided_at,
            "expire_reason": request.expire_reason}
