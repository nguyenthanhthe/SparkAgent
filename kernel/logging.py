"""Logging setup: console + rotating file + event bus (for the dashboard)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Callable

from kernel.bus import EventBus

ROOT_LOGGER = "sparkagent"


class BusHandler(logging.Handler):
    """Forwards formatted records to the ``logs`` bus channel.

    Records may be emitted from worker threads, so publication is always
    marshalled onto the bound event loop via ``call_soon_threadsafe``.
    An optional ``redactor`` masks secret values before they reach the bus.
    """

    def __init__(self, bus: EventBus, redactor: Callable[[str], str] | None = None):
        super().__init__()
        self._bus = bus
        self._redactor = redactor
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            if self._redactor is not None:
                line = self._redactor(line)
            self._bus.publish_threadsafe("logs", line)
        except Exception:  # noqa: BLE001 — logging must never raise
            self.handleError(record)


def setup_logging(level: str = "INFO", logfile: Path | None = None,
                  bus: EventBus | None = None,
                  redactor: Callable[[str], str] | None = None) -> logging.Logger:
    """Configure the ``sparkagent`` logger tree and return its root.

    Pass ``level="json"`` to emit JSON lines on the console (log-shipped
    friendly) instead of the default human-readable format.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    json_mode = str(level).lower() == "json"
    logger.setLevel(logging.INFO if json_mode else
                    getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s "
                                           "%(name)s | %(message)s"))
    logger.addHandler(console)
    if json_mode:
        from kernel.jsonlog import use_json_logging
        use_json_logging(logger)

    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            logfile, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
        logger.addHandler(file_handler)

    if bus is not None:
        logger.addHandler(BusHandler(bus, redactor=redactor))

    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
