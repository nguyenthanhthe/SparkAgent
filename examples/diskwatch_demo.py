"""Diskwatch demo: usage level + top-subdirectory breakdown, offline.

Builds a throwaway data dir with unequally-sized children, then renders
the same report ``python -m ops.diskwatch`` prints — level, thresholds,
and the prune-target hint.

    python examples/diskwatch_demo.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.diskwatch import MB, check_usage, subdirs_top   # noqa: E402


def main() -> None:
    root = Path(tempfile.mkdtemp()) / "data"
    for name, kb in (("logs", 120), ("quarantine", 40), ("backups", 8)):
        child = root / name
        child.mkdir(parents=True)
        (child / "blob.bin").write_bytes(b"x" * kb * 1024)

    report = check_usage(root)
    print(f"data dir : {root}")
    print(f"usage    : {report.total_mb:.1f} MB "
          f"(level: {report.level})")
    print(f"warn at  : {report.warn_threshold_mb:g} MB")
    print(f"critical : {report.critical_threshold_mb:g} MB")
    print("largest subdirs:")
    for item in subdirs_top(root):
        print(f"  {item['dir']:12s} {item['bytes'] / MB:8.1f} MB")


if __name__ == "__main__":
    main()
