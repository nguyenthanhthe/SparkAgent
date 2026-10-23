"""Input validation helpers shared by tools, API handlers, and skills.

Every validator raises :class:`ValidationError` (a non-retryable
:class:`~kernel.errors.SparkError`) with a precise message so the ReAct
loop can surface it as an actionable observation.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from kernel.errors import SparkError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_ABSOLUTE_HTTP_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$",
                                   re.IGNORECASE)


class ValidationError(SparkError):
    def __init__(self, message: str):
        super().__init__(message)


def require_str(value: Any, name: str, *, min_len: int = 1,
                max_len: int = 8000) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string, got "
                              f"{type(value).__name__}")
    if len(value) < min_len:
        raise ValidationError(f"{name} must be at least {min_len} chars")
    if len(value) > max_len:
        raise ValidationError(f"{name} must be at most {max_len} chars")
    return value


def require_int(value: Any, name: str, *, minimum: int | None = None,
                maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            value = int(value)
        else:
            raise ValidationError(f"{name} must be an integer, got "
                                  f"{value!r}")
    if minimum is not None and value < minimum:
        raise ValidationError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValidationError(f"{name} must be <= {maximum}, got {value}")
    return value


def require_number(value: Any, name: str, *, minimum: float | None = None,
                   maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValidationError(f"{name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValidationError(f"{name} must be <= {maximum}")
    return number


def require_dict(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be an object, got "
                              f"{type(value).__name__}")
    return value


def require_keys(mapping: dict, keys: Iterable[str]) -> dict:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValidationError(f"missing required key(s): {missing}")
    return mapping


def require_enum(value: Any, name: str, options: Iterable[Any]) -> Any:
    options = list(options)
    if value not in options:
        raise ValidationError(f"{name} must be one of {options}, got {value!r}")
    return value


def require_identifier(value: Any, name: str) -> str:
    value = require_str(value, name)
    if not _IDENTIFIER_RE.match(value):
        raise ValidationError(
            f"{name} must match {_IDENTIFIER_RE.pattern!r}, got {value!r}")
    return value


def require_http_url(value: Any, name: str) -> str:
    value = require_str(value, name, max_len=2048)
    if not _ABSOLUTE_HTTP_URL_RE.match(value):
        raise ValidationError(f"{name} must be an absolute http(s) URL, "
                              f"got {value!r}")
    return value


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sanitize_multiline(value: str, max_lines: int = 200) -> str:
    """Strip control characters except \\n and \\t; cap line count."""
    cleaned = "".join(ch for ch in value if ch in "\n\t"
                      or ch.isprintable())
    lines = cleaned.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["...[truncated]"]
    return "\n".join(lines)


def validate_tool_args(spec: dict, args: dict) -> dict:
    """Validate ``args`` against a tool parameter spec.

    Spec format matches the registry: ``{param: {"type": ..., "required":
    bool, "enum": [...]}}``. Returns the validated dict; unknown keys are
    rejected so the model cannot smuggle extra handler kwargs.
    """
    args = require_dict(args, "args")
    unknown = set(args) - set(spec)
    if unknown:
        raise ValidationError(f"unknown parameter(s): {sorted(unknown)}")
    for param, rule in spec.items():
        if param not in args:
            if rule.get("required"):
                raise ValidationError(f"missing required parameter {param!r}")
            continue
        value = args[param]
        kind = rule.get("type", "string")
        if kind == "string":
            value = require_str(value, param,
                                min_len=1 if rule.get("required") else 0)
        elif kind == "integer":
            value = require_int(value, param)
        elif kind == "number":
            value = require_number(value, param)
        elif kind == "object":
            value = require_dict(value, param)
        if rule.get("enum"):
            require_enum(value, param, rule["enum"])
        args[param] = value
    return args
