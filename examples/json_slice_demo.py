"""Slice demo: the json_query path-slicing grammar, offline.

``start:stop`` segments bound the walk before the rest of the path
applies — open ends on either side, slices composable with wildcards,
same spread semantics as ``*``.

    python examples/json_slice_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import get_path   # noqa: E402

DOC = {"queue": [{"id": 1, "prio": 5}, {"id": 2, "prio": 1},
                 {"id": 3, "prio": 9}, {"id": 4, "prio": 3}]}


def main() -> None:
    print(f"queue.:.id        -> {get_path(DOC, 'queue.:.id')}")
    print(f"queue.0:2.id      -> {get_path(DOC, 'queue.0:2.id')}")
    print(f"queue.2:.id       -> {get_path(DOC, 'queue.2:.id')}")
    print(f"queue.1:3.prio    -> {get_path(DOC, 'queue.1:3.prio')}")
    # open end = to the end of the list, so 1: is everything but the head
    print(f"queue.1:.prio     -> {get_path(DOC, 'queue.1:.prio')}")


if __name__ == "__main__":
    main()
