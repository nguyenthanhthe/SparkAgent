"""JSON depth demo: shape max_depth and stats depth, offline.

The two depth surfaces of :mod:`tools.json_tool` side by side —
``shape(max_depth=...)`` recursion control and ``stats()['depth']``
container-chain measurement — over the same nested document.

    python examples/json_depth_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import shape, stats   # noqa: E402

DOC = {"service": "sparkagent",
       "meta": {"ok": True, "host": {"name": "gpu-01",
                                     "tags": ["a", "b"]}},
       "items": [{"id": 1, "spec": {"cores": 8}}]}


def render(shape_result: dict) -> str:
    return json.dumps(shape_result, indent=1)


def main() -> None:
    print("stats:")
    info = stats(DOC)
    print(f"  depth={info['depth']} "
          f"leaf_count={info['leaf_count']} "
          f"root_type={info['root_type']}")

    print("\nshape at max_depth=2:")
    print(render(shape(DOC, max_depth=2)))

    print("\nshape at max_depth=4 (default):")
    print(render(shape(DOC, max_depth=4)))

    print("\nshape at max_depth=6 (reaches the leaves):")
    print(render(shape(DOC, max_depth=6)))


if __name__ == "__main__":
    main()
