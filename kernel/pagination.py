"""Offset/limit windowing for API lists.

Small, honest helper: validates bounds, slices sequences or async
generators, and returns a stable envelope (`items`, `next_offset`,
`has_more`) so every list endpoint paginates identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


class InvalidPageError(ValueError):
    pass


@dataclass
class Page:
    items: list[Any]
    offset: int
    limit: int
    total: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def next_offset(self) -> int | None:
        return self.offset + self.limit if self.has_more else None

    def envelope(self) -> dict:
        return {"items": self.items, "offset": self.offset,
                "limit": self.limit, "total": self.total,
                "has_more": self.has_more,
                "next_offset": self.next_offset}


def paginate(sequence: Sequence[Any], offset: int = 0,
             limit: int = DEFAULT_LIMIT) -> Page:
    if offset < 0:
        raise InvalidPageError(f"offset must be >= 0, got {offset}")
    if limit < 1:
        raise InvalidPageError(f"limit must be >= 1, got {limit}")
    limit = min(limit, MAX_LIMIT)
    items = list(sequence[offset:offset + limit])
    return Page(items=items, offset=offset, limit=limit, total=len(sequence))


def parse_paging_params(query: dict[str, str],
                        default_limit: int = DEFAULT_LIMIT) -> tuple[int, int]:
    """Read `offset`/`limit` from request query params with validation."""
    try:
        offset = int(query.get("offset", "0"))
        limit = int(query.get("limit", str(default_limit)))
    except ValueError as exc:
        raise InvalidPageError("offset and limit must be integers") from exc
    return offset, limit
