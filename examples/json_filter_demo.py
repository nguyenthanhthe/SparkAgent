"""Filter demo: the full json_query where-term grammar, offline.

Every comparison operator the ``where`` grammar supports, over one
table of rows — the same grammar the agent uses in filter/sort/group
modes and can re-discover via mode=help.

    python examples/json_filter_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import filter_rows, where_help   # noqa: E402

ROWS = [
    {"name": "report.pdf", "size": 120, "status": "done"},
    {"name": "notes.md", "size": 4, "status": "pending"},
    {"name": "DRAFT.PDF", "size": 90, "status": "done"},
    {"name": "archive.zip", "size": 200, "status": "done"},
]


def run(terms: str) -> list[str]:
    return [r["name"] for r in filter_rows(ROWS, terms)]


def main() -> None:
    print("grammar reference (mode=help):")
    print(json.dumps(where_help(), indent=1))

    print("\nexamples:")
    print(f"  size>=100          -> {run('size>=100')}")
    print(f"  status!=done       -> {run('status!=done')}")
    print(f"  name~=.pdf         -> {run('name~=.pdf')}")
    print(f"  name^=draft        -> {run('name^=draft')}")
    print(f"  name$=.pdf         -> {run('name$=.pdf')}")
    print(f"  status=done;size<150 -> {run('status=done;size<150')}")


if __name__ == "__main__":
    main()
