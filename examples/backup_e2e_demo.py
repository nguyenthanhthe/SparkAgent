"""Backup end-to-end demo: create → list → verify window → drill.

Walks the full backup lifecycle from the runbook against a throwaway
directory, using the same helpers the CLI and dashboard panel share:
create (tagged), list_backups (what /api/backup and telegram /backup
show), whole-window verification (what verify-all does), and a scratch
restore drill. Nothing touches a live data directory.

    python examples/backup_e2e_demo.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.backup import create_backup, list_backups, \
    restore_drill, verify_backup   # noqa: E402


def main() -> None:
    root = Path(tempfile.mkdtemp())
    data = root / "data"
    data.mkdir()
    (data / "sparkagent.db").write_bytes(b"e2e-demo-db")
    (data / "logs").mkdir()
    (data / "logs" / "run.log").write_text("line\n", encoding="utf-8")

    # 1. create — two archives so the window holds history
    first = create_backup(data, root / "backups", tag="pre-upgrade")
    (data / "sparkagent.db").write_bytes(b"e2e-demo-db-v2")
    time.sleep(1.1)   # archive names are second-stamped; make room
    second = create_backup(data, root / "backups", tag="post-upgrade")
    print(f"create   : {first.archive_path.name} (pre-upgrade)")
    print(f"         : {second.archive_path.name} (post-upgrade)")

    # 2. list — what /api/backup, the dashboard panel, and telegram
    #    /backup all show
    listing = list_backups(root / "backups")
    for item in listing["archives"]:
        print(f"list     : {item['name']} · {item['bytes']} B · "
              f"tag={item['tag']}")

    # 3. verify the whole window — what verify-all does
    for item in listing["archives"]:
        manifest = verify_backup(root / "backups" / item["name"])
        print(f"verify   : {item['name']} ok "
              f"({manifest['file_count']} files)")

    # 4. drill — verify + restore into a scratch dir, then clean up
    outcome = restore_drill(second.archive_path)
    print(f"drill    : ok={outcome['ok']} files={outcome['files']} "
          f"tag={outcome['tag']}")

    # 5. tamper check — the window verification must refuse
    corrupt = root / "corrupt.zip"
    corrupt.write_bytes(first.archive_path.read_bytes()[:-4] + b"junk")
    try:
        verify_backup(corrupt)
        print("tamper   : NOT DETECTED (should not happen)")
    except Exception as exc:   # noqa: BLE001 — any refusal is the point
        print(f"tamper   : refused — {type(exc).__name__}")


if __name__ == "__main__":
    main()
