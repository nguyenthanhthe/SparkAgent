"""sqlite_query drill-down demo: recent tasks, then the audit trail.

Uses the same guarded ``lookup()`` as the sqlite_query tool and the
/api/db endpoint — static statements, read-only connection, Python-side
filtering (ADR-0007) — against a throwaway in-memory database:

    python examples/sqlite_drilldown_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.memory import Memory       # noqa: E402
from tools.sqlite_query import lookup  # noqa: E402


async def main() -> None:
    memory = Memory(Path(tempfile.mkdtemp()) / "demo.db",
                    embedder_fn=None, embed_dim=64)
    await memory.connect()
    try:
        await memory.submit_task("check gpu thermals", "demo")
        await memory.submit_task("rotate logs", "demo")
        await memory.audit("demo", "task.submit", "#1 check gpu thermals")
        await memory.audit("demo", "task.submit", "#2 rotate logs")

        tasks = await lookup(memory.db_path, "tasks", limit=5)
        print(f"tasks ({tasks['count']} rows, scanned {tasks['scanned']}):")
        for row in tasks["rows"]:
            print(f"  #{row['id']} [{row['status']}] {row['goal']}")

        audit = await lookup(memory.db_path, "audit",
                             where={"actor": "demo"},
                             order_by="id", descending=True, limit=2)
        print(f"audit for actor=demo ({audit['count']} rows):")
        for row in audit["rows"]:
            print(f"  {row['created_at']} {row['action']}: "
                  f"{row['detail']}")

        done = await lookup(memory.db_path, "tasks",
                            where={"status": "pending"}, columns=["goal"])
        print(f"pending goals: {[r['goal'] for r in done['rows']]}")
    finally:
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
