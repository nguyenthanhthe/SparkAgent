"""Stats demo: json_query mode=stats with per-key leaf counts.

The document-census surface — root type, totals, depth, and the
leaves_by_key split that sums to leaf_count — over one nested payload.

    python examples/json_stats_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import stats   # noqa: E402

DOC = {"meta": {"ok": True, "host": {"name": "gpu-01"}},
       "items": [{"id": 1, "spec": {"cores": 8}},
                 {"id": 2, "spec": {"cores": 16}}],
       "note": "single scalar"}


def main() -> None:
    info = stats(DOC)
    print(f"root_type : {info['root_type']}")
    print(f"leaf_count: {info['leaf_count']} "
          f"(depth {info['depth']})")
    print("leaves_by_key:")
    for key, count in info["leaves_by_key"].items():
        print(f"  {key:8s} {count}")
    total = sum(info["leaves_by_key"].values())
    print(f"  sum     {total} == leaf_count: "
          f"{total == info['leaf_count']}")


if __name__ == "__main__":
    main()
