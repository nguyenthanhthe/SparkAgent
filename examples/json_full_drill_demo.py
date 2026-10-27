"""json_query full drill: stats → filter → sort → pluck.

One pass over episode-shaped rows using every row-oriented mode in
order: profile the shape, keep the interesting rows, order them, then
extract a column. The composition the ReAct core would use to answer
"which episodes keep failing and how bad are they?".

    python examples/json_full_drill_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stdlib_tools   # noqa: E402
from tools.registry import ToolContext, ToolRegistry   # noqa: E402

EPISODES = [
    {"id": 41, "goal": "digest telemetry", "status": "failed",
     "steps": 9, "tier": "remote"},
    {"id": 42, "goal": "rotate logs", "status": "done",
     "steps": 3, "tier": "local"},
    {"id": 43, "goal": "verify backups", "status": "done",
     "steps": 5, "tier": "local"},
    {"id": 44, "goal": "vacuum sqlite", "status": "failed",
     "steps": 12, "tier": "remote"},
    {"id": 45, "goal": "archive skills", "status": "done",
     "steps": 4, "tier": "local"},
]


async def main() -> None:
    registry = ToolRegistry()
    stdlib_tools.register_tools(registry)
    ctx = ToolContext()
    payload = json.dumps(EPISODES)

    async def call(**kwargs) -> str:
        return await registry.call(
            "json_query", {"data": payload, **kwargs}, ctx)

    print("1. stats — shape of the batch:")
    print(await call(mode="stats"))

    print("\n2. filter — failed episodes only:")
    print(await call(mode="filter", where="status=failed"))

    print("\n3. sort — failures by step count, worst first:")
    print(await call(mode="sort", sort_by="steps",
                     where="status=failed", descending=True))

    print("\n4. pluck — the goals that need attention:")
    print(await call(mode="pluck", sort_by="goal",
                     where="status=failed"))

    print("\n5. group — tier spend of failures:")
    print(await call(mode="group", sort_by="tier", where="status=failed"))


if __name__ == "__main__":
    asyncio.run(main())
