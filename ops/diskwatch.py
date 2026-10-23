"""Disk usage watch for the SparkAgent data directory.

The agent writes logs, SQLite, quarantine, and sandbox files 24/7; an
unattended leak (verbose logging, a looping skill) can fill a laptop
disk. ``check_usage`` measures the tree and flags thresholds so the
housekeeping loop can alert before the filesystem does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

KB = 1024
MB = 1024 * KB
DEFAULT_WARN_MB = 1024.0
DEFAULT_CRITICAL_MB = 4096.0


@dataclass
class UsageReport:
    total_bytes: int
    warn_threshold_mb: float
    critical_threshold_mb: float

    @property
    def total_mb(self) -> float:
        return self.total_bytes / MB

    @property
    def level(self) -> str:
        if self.total_mb >= self.critical_threshold_mb:
            return "critical"
        if self.total_mb >= self.warn_threshold_mb:
            return "warn"
        return "ok"

    def to_dict(self) -> dict:
        return {"total_mb": round(self.total_mb, 1), "level": self.level,
                "warn_threshold_mb": self.warn_threshold_mb,
                "critical_threshold_mb": self.critical_threshold_mb}


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue        # vanished mid-walk; ignore
    return total


def check_usage(data_dir: Path, warn_mb: float = DEFAULT_WARN_MB,
                critical_mb: float = DEFAULT_CRITICAL_MB) -> UsageReport:
    total = dir_size(data_dir) if data_dir.exists() else 0
    return UsageReport(total_bytes=total, warn_threshold_mb=warn_mb,
                       critical_threshold_mb=critical_mb)
