"""json_query operator cheat sheet: one-liners over task rows.

Each block is a copy-pasteable tool call an operator (or the agent)
would actually make — the answers to the questions that come up every
shift, expressed in json_query modes.

    python examples/json_query_cheatsheet_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stdlib_tools   # noqa: E402
from tools.registry import ToolContext, ToolRegistry   # noqa: E402

TASKS = [
    {"id": 1, "goal": "nightly digest", "status": "done", "enabled": 1,
     "priority": 5},
    {"id": 2, "goal": "gpu health check", "status": "failed",
     "enabled": 1, "priority": 1},
    {"id": 3, "goal": "vacuum sqlite", "status": "pending", "enabled": 0,
     "priority": 3},
    {"id": 4, "goal": "archive skills", "status": "done", "enabled": 1,
     "priority": 4},
]


async def main() -> None:
    registry = ToolRegistry()
    stdlib_tools.register_tools(registry)
    ctx = ToolContext()
    payload = json.dumps(TASKS)

    async def call(**kwargs) -> str:
        return await registry.call(
            "json_query", {"data": payload, **kwargs}, ctx)

    recipes = [
        ("how many tasks per status?",
         {"mode": "group", "sort_by": "status"}),
        ("what is failing?",
         {"mode": "filter", "where": "status=failed"}),
        ("enabled tasks, highest priority first:",
         {"mode": "sort", "where": "enabled=1", "sort_by": "priority",
          "descending": True}),
        ("id of every enabled task:",
         {"mode": "pluck", "where": "enabled=1", "sort_by": "id"}),
        ("distinct statuses:",
         {"mode": "unique", "sort_by": "status"}),
        ("goal starting with 'gpu':",
         {"mode": "filter", "where": "goal^=gpu"}),
        ("what filters exist? (ask the tool):",
         {"mode": "help"}),
    ]
    for question, kwargs in recipes:
        answer = await call(**kwargs)
        print(f"Q: {question}")
        print(f"A: {answer}\n")


if __name__ == "__main__":
    asyncio.run(main())
