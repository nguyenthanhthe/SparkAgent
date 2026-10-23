"""JSON-lines log formatting for machine consumption.

Enable with ``logging.level: json`` in config (or
``SPARKAGENT_LOGGING__LEVEL=json``): the console handler switches to one
JSON object per line — timestamp, level, logger, message, plus trace id
when a span is active — which log shippers parse without regexes. The
plain-text format remains the default for humans.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kernel.correlation import current_span

RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, extra_fields: dict[str, Any] | None = None):
        super().__init__()
        self.extra_fields = dict(extra_fields or {})

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        span = current_span()
        if span is not None:
            payload["trace_id"] = span.trace_id
            payload["span"] = span.name
        for key, value in record.__dict__.items():
            if key not in RESERVED and not key.startswith("_") \
                    and key not in payload:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)
        payload.update(self.extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)[:2000]
        return json.dumps(payload, ensure_ascii=False)


def use_json_logging(logger: logging.Logger,
                     extra_fields: dict[str, Any] | None = None) -> None:
    """Swap the logger's console (non-file) handlers to JSON output."""
    formatter = JsonFormatter(extra_fields)
    swapped = 0
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and \
                not isinstance(handler, logging.FileHandler):
            handler.setFormatter(formatter)
            swapped += 1
    if swapped == 0:
        logger.warning("no console handler found; JSON logging not applied")


def looks_like_json_log(line: str) -> bool:
    """Quick heuristic used by tools/tests to classify log lines."""
    stripped = line.strip()
    return stripped.startswith("{") and stripped.endswith("}") and \
        '"message"' in stripped
