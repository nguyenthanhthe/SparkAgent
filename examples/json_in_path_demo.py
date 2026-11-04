"""JSON in_path search demo: locating list positions offline.

The ``in_path`` toggle of :func:`tools.json_tool.search` matches the
needle as a literal substring against the accumulated dotted path —
so list positions (``items.0``) and multi-segment fragments
(``items.0.name``) can be located directly, beyond key/value matching.

    python examples/json_in_path_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import search   # noqa: E402

DOC = {"service": "sparkagent",
       "items": [
           {"id": 1, "name": "sensor node", "tags": ["a", "b"]},
           {"id": 2, "name": "gateway", "tags": ["c"]},
       ]}


def main() -> None:
    print("document:")
    print(json.dumps(DOC, indent=1))

    print("\nsearch('gateway') — keys+values only (in_path off):")
    for hit in search(DOC, "gateway"):
        print(f"  {hit}")

    print("\nsearch('items.0', in_path=True) — list position as text:")
    for hit in search(DOC, "items.0", in_path=True):
        print(f"  {hit}")

    print("\nsearch('tags', in_path=True) — parent fragment match:")
    for hit in search(DOC, "items.1.tags", in_path=True):
        print(f"  {hit}")

    print("\nneedle is literal text, never a regex — "
          "search('items.0.name', in_path=True):")
    for hit in search(DOC, "items.0.name", in_path=True):
        print(f"  {hit}")


if __name__ == "__main__":
    main()
