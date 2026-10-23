"""Correlation IDs and lightweight span tracing.

Every episode, task, and tool call gets a trace ID; nested operations get
span IDs. IDs propagate via ``contextvars`` so they survive awaits and
``asyncio.to_thread`` without explicit plumbing, and appear in logs via
``current()``.
"""

from __future__ import annotations

import contextvars
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


def new_id(length: int = 12) -> str:
    """URL-safe short id (24^12 ≈ 4.7e16 options, prefix-free)."""
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float | None:
        return None if self.ended_at is None else self.ended_at - self.started_at

    def finish(self) -> "Span":
        if self.ended_at is None:
            self.ended_at = time.monotonic()
        return self

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "span_id": self.span_id,
                "parent_id": self.parent_id, "name": self.name,
                "duration_s": (round(self.duration_s, 4)
                               if self.duration_s is not None else None),
                "attributes": self.attributes}


_current_span: contextvars.ContextVar[Span | None] = \
    contextvars.ContextVar("sparkagent_span", default=None)


def current_span() -> Span | None:
    return _current_span.get()


def current_trace_id() -> str | None:
    span = _current_span.get()
    return span.trace_id if span else None


@contextmanager
def trace(name: str, trace_id: str | None = None,
          attributes: dict[str, Any] | None = None) -> Iterator[Span]:
    """Open a root trace (or a named span under the current trace)."""
    parent = _current_span.get()
    span = Span(trace_id=trace_id or (parent.trace_id if parent else new_id()),
                span_id=new_id(),
                parent_id=parent.span_id if parent else None,
                name=name,
                attributes=dict(attributes or {}))
    token = _current_span.set(span)
    try:
        yield span
    finally:
        span.finish()
        _current_span.reset(token)


class TraceLog:
    """Collects finished spans for the current episode (bounded)."""

    def __init__(self, max_spans: int = 1000):
        self.max_spans = max_spans
        self.spans: list[dict] = []

    def record(self, span: Span) -> None:
        self.spans.append(span.to_dict())
        if len(self.spans) > self.max_spans:
            del self.spans[: len(self.spans) - self.max_spans]

    def summary(self) -> dict:
        durations = [s["duration_s"] for s in self.spans
                     if s.get("duration_s") is not None]
        total = sum(durations) if durations else 0.0
        by_name: dict[str, int] = {}
        for span in self.spans:
            by_name[span["name"]] = by_name.get(span["name"], 0) + 1
        return {"span_count": len(self.spans),
                "recorded_seconds": round(total, 4),
                "by_name": by_name}
