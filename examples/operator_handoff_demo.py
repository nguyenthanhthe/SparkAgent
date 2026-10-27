"""Operator handoff demo: one report across status, backups, quarantine.

Prints the shift-handoff summary an outgoing operator would leave: the
daemon status snapshot, the backup window with a verification of the
newest archive, the quarantine top reasons, and the recent audit trail —
all against throwaway state through the guarded implementations.

    python examples/operator_handoff_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.config import Config   # noqa: E402
from kernel.daemon import AgentDaemon   # noqa: E402
from ops.backup import create_backup, verify_backup   # noqa: E402


async def main() -> None:
    root = Path(tempfile.mkdtemp())
    daemon = AgentDaemon(Config(
        {"agent": {"name": "handoff-demo"},
         "memory": {"db_path": str(root / "t.db")}},
        root=root))
    await daemon.memory.connect()
    try:
        # stage realistic state: a task, a backup, a quarantined fetch
        await daemon.memory.submit_task("nightly digest", "cron")
        data = root / "data"
        data.mkdir(exist_ok=True)
        (data / "sparkagent.db").write_bytes(b"handoff")
        backup = create_backup(data, root / "backups", tag="nightly")
        daemon.quarantine.put("injection payload", "prompt-injection risk")
        await daemon.memory.audit("operator", "quarantine.put",
                                  "prompt-injection risk")

        status = daemon.status()
        print(f"=== handoff report — {status['agent']} "
              f"v{status['version']} ===")
        print(f"uptime    : {status['uptime_s']}s")
        print(f"tasks     : {status['scheduler'].get('blocked_tasks', 0)} "
              f"blocked")
        q = status["quarantine"]
        print(f"quarantine: {q['items']} item(s), top reasons "
              f"{q['top_reasons']}")

        manifest = verify_backup(backup.archive_path)
        print(f"backups   : {backup.archive_path.name} "
              f"({manifest['file_count']} files, tag=nightly, verified)")

        rows = await daemon.memory.recent_audit(limit=3)
        print("audit     :")
        for row in rows:
            print(f"  {row['created_at'][11:]} {row['actor']} "
                  f"{row['action']} {str(row.get('detail') or '')[:40]}")
    finally:
        await daemon.memory.close()


if __name__ == "__main__":
    asyncio.run(main())
