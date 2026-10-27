"""Status page demo: daemon.status() rendered as text, offline.

Shows what /api/status and the dashboard header see, without a daemon:
an AgentDaemon over a temp database, one task submitted, a quarantined
item parked, then the status payload printed as key/value lines — the
same numbers the operator monitors.

    python examples/status_page_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.config import Config   # noqa: E402
from kernel.daemon import AgentDaemon   # noqa: E402


async def main() -> None:
    daemon = AgentDaemon(Config(
        {"agent": {"name": "status-demo"},
         "memory": {"db_path": str(Path(tempfile.mkdtemp()) / "t.db")}},
        root=Path(tempfile.mkdtemp())))
    await daemon.memory.connect()
    try:
        await daemon.memory.submit_task("demo task", "demo")
        daemon.quarantine.put("suspicious body", "prompt-injection risk")
        status = daemon.status()
        print(f"agent     : {status['agent']} v{status['version']}")
        print(f"uptime    : {status['uptime_s']}s")
        sched = status["scheduler"]
        print(f"scheduler : {sched['episodes_done']} done / "
              f"{sched['episodes_failed']} failed, "
              f"{sched.get('blocked_tasks', 0)} blocked")
        q = status["quarantine"]
        print(f"quarantine: {q['items']} item(s), {q['bytes']} bytes, "
              f"oldest {q['oldest_age_s']}s")
        print(f"tools     : {len(status['tools'])} registered")
        print(f"vault     : unlocked={status['vault_unlocked']}")
    finally:
        await daemon.memory.close()


if __name__ == "__main__":
    asyncio.run(main())
