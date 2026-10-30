"""Rename demo: memory key repair via /api/memories/rename, offline.

An operator mistyped a memory key twice; the rename endpoint re-keys
every row in one audited action — the audit line carries the affected
row count (Wave AL-3). Uses the real Memory + the real endpoint via the
TestClient, no network.

    python examples/rename_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from interface.web import build_web_app
    from kernel.config import Config
    from kernel.daemon import AgentDaemon

    daemon = AgentDaemon(Config(
        {"memory": {"db_path": str(Path(tempfile.mkdtemp()) / "t.db")}},
        root=Path(tempfile.mkdtemp())))
    await daemon.memory.connect()
    client = TestClient(TestServer(build_web_app(daemon)))
    await client.start_server()
    try:
        await daemon.memory.remember("gpu cap at 85c", key="gpu_thresold")
        await daemon.memory.remember("gpu cap followup", key="gpu_thresold")
        print("seeded 2 memories under the mistyped key 'gpu_thresold'")

        resp = await client.post("/api/memories/rename",
                                 json={"old": "gpu_thresold",
                                       "new": "gpu_threshold"})
        body = await resp.json()
        print(f"rename -> {body}")

        rows = await daemon.memory.recent_audit(limit=5)
        audit = next(r for r in rows if r["action"] == "memory.rename_key")
        print(f"audit  -> {audit['action']}: {audit['detail']}")

        resp = await client.post("/api/memories/rename",
                                 json={"old": "gpu_threshold",
                                       "new": "gpu_threshold"})
        print(f"same-key guard -> HTTP {resp.status}")
    finally:
        await client.close()
        await daemon.memory.close()


if __name__ == "__main__":
    asyncio.run(main())
