"""Lifecycle demo: a subscriber watches daemon_stopping.

Runs a tiny AgentDaemon over a temp database, subscribes to the
lifecycle channel, then stops the daemon — the subscriber receives the
daemon_stopping event before the coroutine returns. This is the same
channel the web layer could use to announce shutdown to clients.

    python examples/lifecycle_demo.py
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
        {"agent": {"name": "lifecycle-demo"},
         "memory": {"db_path": str(Path(tempfile.mkdtemp()) / "t.db")}},
        root=Path(tempfile.mkdtemp())))
    await daemon.memory.connect()
    queue = daemon.bus.subscribe("lifecycle")
    try:
        print("daemon  : running (press nothing, we stop right away)")
        await daemon.stop()
        while not queue.empty():
            event = queue.get_nowait()
            print(f"lifecycle: {event['event']}")
    finally:
        await daemon.memory.close()


if __name__ == "__main__":
    asyncio.run(main())
