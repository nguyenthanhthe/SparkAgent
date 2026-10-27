"""json_query filter + sort drill demo: triage task rows offline.

Feeds a realistic batch of task rows through the json_query tool the
same way the ReAct core would: filter mode keeps the interesting rows
(comparison terms like age>=30), sort mode orders what's left. No
database, no daemon — the tool's pure functions over JSON text.

    python examples/json_query_drill_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.registry import ToolContext, ToolRegistry   # noqa: E402
from tools import stdlib_tools   # noqa: E402

TASKS = [
    {"id": 12, "goal": "digest gpu telemetry", "priority": 2,
     "retries": 1, "blocked_by": [7]},
    {"id": 15, "goal": "rotate logs", "priority": 5,
     "retries": 0, "blocked_by": []},
    {"id": 19, "goal": "verify backup window", "priority": 1,
     "retries": 2, "blocked_by": []},
    {"id": 21, "goal": "vacuum sqlite", "priority": 3,
     "retries": 0, "blocked_by": [15]},
]


async def main() -> None:
    registry = ToolRegistry()
    stdlib_tools.register_tools(registry)
    ctx = ToolContext()
    payload = json.dumps(TASKS)

    async def call(**kwargs) -> str:
        return await registry.call(
            "json_query", {"data": payload, **kwargs}, ctx)

    print("all rows:")
    print(await call(mode="stats"))

    print("\nfilter: priority<=2;retries>=1  (urgent and already flaky)")
    print(await call(mode="filter", where="priority<=2;retries>=1"))

    print("\nsort: rows by priority, ascending")
    print(await call(mode="sort", sort_by="priority"))

    print("\nsort descending by retries")
    print(await call(mode="sort", sort_by="retries", descending=True))


if __name__ == "__main__":
    asyncio.run(main())
