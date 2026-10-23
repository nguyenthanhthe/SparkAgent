"""Kernel exception hierarchy.

Every subsystem raises a subclass of :class:`SparkError` so callers can
distinguish agent-framework failures from tool-level failures and plain
programming errors. Recoverable errors carry ``retryable`` so generic
retry/circuit policies can act without knowing the subsystem.
"""

from __future__ import annotations


class SparkError(Exception):
    """Base class for all SparkAgent errors."""

    retryable: bool = False

    def __init__(self, message: str, *, retryable: bool | None = None):
        super().__init__(message)
        if retryable is not None:
            self.retryable = retryable

    @property
    def code(self) -> str:
        return type(self).__name__


class ConfigurationError(SparkError):
    """Invalid or missing configuration."""


class PersistenceError(SparkError):
    """SQLite/storage layer failure."""


class BrainError(SparkError):
    """LLM tier failure."""


class BrainOverloadedError(BrainError):
    """Tier temporarily out of capacity (retryable)."""

    retryable = True


class ToolFailure(SparkError):
    """A tool rejected its input or failed internally (becomes an observation)."""


class SandboxViolation(SparkError):
    """A command/path violated the OpenShell policy."""


class RateLimitedError(SparkError):
    """A rate limit was exceeded (retryable after the delay)."""

    retryable = True

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class ApprovalRequired(SparkError):
    """An action needs operator approval before proceeding."""

    def __init__(self, message: str, approval_id: str):
        super().__init__(message)
        self.approval_id = approval_id
