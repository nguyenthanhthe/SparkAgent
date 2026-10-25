"""Task dependency demo: a chain submits, blocks, then releases.

Shows ADR-0006 in action offline: task B depends on task A, so B stays
out of the due list (blocked_by shows A) until A settles to done.

    python examples/dependency_chain_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.memory import Memory   # noqa: E402


async def main() -> None:
    memory = Memory(Path(tempfile.mkdtemp()) / "demo.db",
                    embedder_fn=None, embed_dim=64)
    await memory.connect()
    try:
        fetch = await memory.submit_task("fetch gpu telemetry", "demo")
        digest = await memory.submit_task("digest gpu telemetry", "demo",
                                          depends_on=[fetch])

        due = await memory.due_tasks(now=9999999999.0)
        print(f"due now      : {[t['goal'] for t in due]}")
        print(f"digest blocked by: {await memory.blocked_by(digest)}")

        await memory.mark_task_running(fetch)
        await memory.finish_task(fetch, success=True)

        due = await memory.due_tasks(now=9999999999.0)
        print(f"due now      : {[t['goal'] for t in due]}")
        print(f"digest blocked by: {await memory.blocked_by(digest)}")
    finally:
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
