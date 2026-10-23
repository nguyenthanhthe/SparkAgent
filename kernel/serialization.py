"""Safe serialization for logs, API payloads, and model observations.

``safe_json`` never raises: non-serializable values become repr strings,
circular references are cut at a depth cap, and an optional redactor masks
secrets in every string before it ships. Output size is bounded.
"""

from __future__ import annotations

import json
from typing import Any, Callable

MAX_DEPTH = 8
MAX_CHARS = 16_384


def _safe_value(value: Any, depth: int, redactor: Callable[[str], str] | None,
                seen: tuple[int, ...]) -> Any:
    if depth > MAX_DEPTH:
        return "…[depth cap]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            if redactor is not None:
                value = redactor(value)
            return value if len(value) <= MAX_CHARS else \
                value[:MAX_CHARS] + "…[truncated]"
        return value
    obj_id = id(value)
    if obj_id in seen:
        return "…[circular]"
    if isinstance(value, dict):
        return {str(k)[:200]: _safe_value(v, depth + 1, redactor,
                                          seen + (obj_id,))
                for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v, depth + 1, redactor, seen + (obj_id,))
                for v in list(value)[:1000]]
    # dataclass-ish objects with __dict__
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {"__type__": type(value).__name__,
                **{str(k)[:100]: _safe_value(v, depth + 1, redactor,
                                             seen + (obj_id,))
                   for k, v in list(vars(value).items())[:50]}}
    return repr(value)[:200]


def safe_json(value: Any, *, indent: int | None = None,
              redactor: Callable[[str], str] | None = None) -> str:
    """Serialize anything to JSON without raising; strings redacted."""
    try:
        return json.dumps(_safe_value(value, 0, redactor, ()),
                          ensure_ascii=False, indent=indent, default=str)
    except (TypeError, ValueError, RecursionError):
        return json.dumps({"error": "unserializable",
                           "repr": repr(value)[:500]})


def safe_parse(text: str) -> Any:
    """Parse JSON defensively: raises ValueError with context on failure."""
    if not isinstance(text, str):
        raise ValueError(f"expected str, got {type(text).__name__}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        preview = text[:120].replace("\n", "\\n")
        raise ValueError(f"invalid JSON ({exc.msg} at pos {exc.pos}): "
                         f"{preview!r}") from exc


def compact_repr(value: Any, limit: int = 300) -> str:
    """Human repr, length-capped, never raising."""
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 — repr can be hostile
        return "<unrepr-able>"
    return text if len(text) <= limit else text[:limit - 12] + "…[truncated]"
