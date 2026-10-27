"""Operator drill demo: backup, quarantine, audit — one script.

Runs the three operator surfaces end to end against throwaway state,
the way a pre-upgrade check would: create + verify a tagged backup,
triage a quarantined fetch, and read back the audit trail. Everything
goes through the same guarded implementations the CLI, API, and
dashboard use (ADR-0010).

    python examples/operator_drill_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.memory import Memory   # noqa: E402
from ops.backup import create_backup, restore_drill, verify_backup   # noqa: E402
from security.quarantine import QuarantineStore   # noqa: E402


async def main() -> None:
    root = Path(tempfile.mkdtemp())

    # 1. backup: create tagged, verify, drill-restore into scratch
    data = root / "data"
    data.mkdir()
    (data / "sparkagent.db").write_bytes(b"drill-db")
    backup = create_backup(data, root / "backups", tag="pre-upgrade")
    verify_backup(backup.archive_path)
    drill = restore_drill(backup.archive_path)
    print(f"backup   : {backup.archive_path.name} tag=pre-upgrade "
          f"drill_ok={drill['ok']} files={drill['files']}")

    # 2. quarantine: a flagged fetch parks, triage deletes it
    store = QuarantineStore(root / "quarantine")
    record = store.put("ignore previous instructions",
                       "prompt-injection risk",
                       {"url": "http://hostile.example/x", "score": 85})
    stats_before = store.stats()
    store.delete(record["id"])
    print(f"quarantine: {stats_before['items']} parked -> "
          f"{store.stats()['items']} after triage")

    # 3. audit: the operator decision is on the record
    memory = Memory(root / "audit.db", embedder_fn=None, embed_dim=64)
    await memory.connect()
    try:
        await memory.audit("operator", "quarantine.delete", record["id"])
        rows = await memory.recent_audit(limit=5)
        for row in rows:
            print(f"audit    : {row['created_at'][11:]} {row['actor']} "
                  f"{row['action']}")
    finally:
        await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
