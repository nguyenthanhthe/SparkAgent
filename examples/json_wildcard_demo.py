"""Wildcard demo: spread semantics + slice ranges in json_query paths.

``*`` spreads across lists/dicts; ``start:stop`` slices bound the walk
before it spreads — one document, the four path shapes the agent uses
to interrogate API responses.

    python examples/json_wildcard_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import get_path   # noqa: E402

DOC = {"hosts": [
    {"name": "web-01", "tags": ["emea", "web"]},
    {"name": "web-02", "tags": ["apac", "web"]},
    {"name": "db-01", "tags": ["emea", "db"]},
]}


def main() -> None:
    print(f"hosts.*.name        -> {get_path(DOC, 'hosts.*.name')}")
    print(f"hosts.0:2.name      -> {get_path(DOC, 'hosts.0:2.name')}")
    print(f"hosts.:1.tags       -> {get_path(DOC, 'hosts.:1.tags')}")
    # spread through the slice: every tag of the first two hosts
    print(f"hosts.0:2.tags.*    -> {get_path(DOC, 'hosts.0:2.tags.*')}")
    print(f"hosts.2:.name       -> {get_path(DOC, 'hosts.2:.name')}")


if __name__ == "__main__":
    main()
