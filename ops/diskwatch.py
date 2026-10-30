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
        return {"bytes_total": self.total_bytes,
                "total_mb": round(self.total_mb, 1), "level": self.level,
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


def subdirs_top(path: Path, keep: int = 3) -> list[dict]:
    """Immediate subdirectories ranked by size (top ``keep``) — the
    prune-target hint: which child to clean when the level goes warn."""
    sizes = []
    for child in path.iterdir():
        if child.is_dir():
            sizes.append({"dir": child.name, "bytes": dir_size(child)})
    sizes.sort(key=lambda item: -item["bytes"])
    return sizes[:keep]


def check_usage(data_dir: Path, warn_mb: float = DEFAULT_WARN_MB,
                critical_mb: float = DEFAULT_CRITICAL_MB) -> UsageReport:
    total = dir_size(data_dir) if data_dir.exists() else 0
    return UsageReport(total_bytes=total, warn_threshold_mb=warn_mb,
                       critical_threshold_mb=critical_mb)


def main(argv: list[str] | None = None) -> int:
    """CLI entry (``python -m ops.diskwatch``): measure and report usage.

    Exit codes let scheduled tasks react without parsing output:
    0 = ok, 1 = warn, 2 = critical, 3 = error."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m ops.diskwatch",
        description="Report SparkAgent data-directory disk usage.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="directory to measure (default: ./data)")
    parser.add_argument("--warn-mb", type=float, default=DEFAULT_WARN_MB,
                        help=f"warn threshold in MB "
                             f"(default: {DEFAULT_WARN_MB:g})")
    parser.add_argument("--critical-mb", type=float,
                        default=DEFAULT_CRITICAL_MB,
                        help=f"critical threshold in MB "
                             f"(default: {DEFAULT_CRITICAL_MB:g})")
    parser.add_argument("--json", action="store_true",
                        help="emit the UsageReport as JSON")
    args = parser.parse_args(argv)

    if args.critical_mb < args.warn_mb:
        print("error: --critical-mb must be >= --warn-mb", file=sys.stderr)
        return 3
    if not args.data_dir.is_dir():
        print(f"error: data dir not found: {args.data_dir}", file=sys.stderr)
        return 3

    report = check_usage(args.data_dir, warn_mb=args.warn_mb,
                         critical_mb=args.critical_mb)
    top = subdirs_top(args.data_dir)
    if args.json:
        payload = report.to_dict()
        payload["subdirs_top"] = top
        print(json.dumps(payload, indent=2))
    else:
        print(f"data dir : {args.data_dir}")
        print(f"usage    : {report.total_mb:.1f} MB")
        print(f"warn at  : {report.warn_threshold_mb:g} MB")
        print(f"critical : {report.critical_threshold_mb:g} MB")
        print(f"level    : {report.level}")
        for item in top:
            print(f"  {item['dir']:20s} {item['bytes'] / MB:8.1f} MB")
        if report.level == "warn" and top:
            print(f"tip      : prune target — {top[0]['dir']} "
                  f"({top[0]['bytes'] / MB:.1f} MB), the largest subdir")
        if report.level == "critical":
            print("tip      : prune logs/quarantine, then rerun; a "
                  "runaway skill is the usual cause (check the audit "
                  "trail for loops)")
    return {"ok": 0, "warn": 1, "critical": 2}[report.level]


if __name__ == "__main__":
    import sys
    sys.exit(main())
