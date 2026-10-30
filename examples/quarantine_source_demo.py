"""Quarantine source demo: the stats source breakdown, offline.

Items park with a source label (ADR-0012); the aggregate view shows
which producer contributes what — the same snapshot /api/status and
the dashboard read.

    python examples/quarantine_source_demo.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security.quarantine import QuarantineStore   # noqa: E402


def main() -> None:
    store = QuarantineStore(Path(tempfile.mkdtemp()) / "quarantine")
    store.put("page one body", "prompt-injection risk",
              {"url": "http://8.8.8.8/a"}, source="web_fetch")
    store.put("page two body", "prompt-injection risk",
              {"url": "http://8.8.8.8/b"}, source="web_fetch")
    store.put("giant skill", "oversized skill proposal",
              source="skillforge")
    store.put("legacy blob", "unclassified")   # default label

    stats = store.stats()
    print(f"items={stats['items']} bytes={stats['bytes']} "
          f"oldest={stats['oldest_human']}")
    print("by_source:")
    for source, count in stats["by_source"].items():
        print(f"  {source:12s} {count}")
    print("top_reasons:")
    for reason, count in stats["top_reasons"].items():
        print(f"  {reason:20s} {count}")

    got = store.get(stats and store.list()[0]["id"])
    print(f"newest item age: {got['age_human']} "
          f"(source={got['record']['source']})")


if __name__ == "__main__":
    main()
