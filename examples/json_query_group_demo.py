"""json_query group demo: triage quarantine records offline.

Feeds synthetic quarantine records through mode=group the way an
operator would summarize a real quarantine listing: counts per reason,
then a filter+group combo for one reason kind. Pairs with the
/api/quarantine?reason= endpoint (server-side filter).

    python examples/json_query_group_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stdlib_tools   # noqa: E402
from tools.registry import ToolContext, ToolRegistry   # noqa: E402

RECORDS = [
    {"id": "q1", "reason": "prompt-injection risk", "score": 80,
     "bytes": 1200},
    {"id": "q2", "reason": "prompt-injection risk", "score": 45,
     "bytes": 300},
    {"id": "q3", "reason": "oversized skill proposal", "score": 0,
     "bytes": 600000},
    {"id": "q4", "reason": "prompt-injection risk", "score": 55,
     "bytes": 900},
    {"id": "q5", "reason": "manual operator hold", "score": 0,
     "bytes": 100},
]


async def main() -> None:
    registry = ToolRegistry()
    stdlib_tools.register_tools(registry)
    ctx = ToolContext()
    payload = json.dumps(RECORDS)

    async def call(**kwargs) -> str:
        return await registry.call(
            "json_query", {"data": payload, **kwargs}, ctx)

    print("group by reason:")
    print(await call(mode="group", sort_by="reason"))

    print("\nhigh-score items only (score>=40), grouped:")
    print(await call(mode="group", sort_by="reason",
                     where="score>=40"))

    print("\nbiggest quarantined blob (sort by bytes, last):")
    print(await call(mode="sort", sort_by="bytes"))


if __name__ == "__main__":
    asyncio.run(main())
