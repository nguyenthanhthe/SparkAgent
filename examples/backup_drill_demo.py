"""Backup drill demo: create, verify, tamper-check, restore.

Exercises ops/backup.py offline against a throwaway data directory —
the same create/verify/restore path the CLI (`python -m ops.backup`)
and the retention window use. Run it as a periodic restore drill: a
backup you have never restored is a hope, not a backup.

    python examples/backup_drill_demo.py
"""

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.backup import BackupError, create_backup, restore_backup, \
    verify_backup   # noqa: E402


def main() -> None:
    root = Path(tempfile.mkdtemp())
    data = root / "data"
    (data / "logs").mkdir(parents=True)
    (data / "sparkagent.db").write_bytes(b"demo-database-bytes")
    (data / "logs" / "run.log").write_text("line one\n", encoding="utf-8")

    # 1. create — vault secrets excluded by default
    result = create_backup(data, root / "backups", tag="drill")
    print(f"created   : {result.archive_path.name}")
    print(f"files     : {result.file_count}, {result.total_bytes} bytes")
    print(f"digest    : {result.digest[:16]}…")

    # 2. verify — manifest + per-file SHA-256 + whole-set digest
    manifest = verify_backup(result.archive_path)
    print(f"verified  : {manifest['file_count']} files, "
          f"tag={manifest.get('tag')}")

    # 3. restore — hashes are checked before a single byte is written
    target = root / "restored"
    outcome = restore_backup(result.archive_path, target)
    print(f"restored  : {outcome['restored_files']} files "
          f"({outcome['total_bytes']} bytes)")
    assert (target / "sparkagent.db").read_bytes() == b"demo-database-bytes"
    print("roundtrip : byte-identical ✓")

    # 4. tamper check — rewrite one entry with different content;
    #    verification must refuse before restore ever touches disk
    corrupt = root / "corrupt.zip"
    with zipfile.ZipFile(result.archive_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["logs/run.log"] = b"tampered line\n"
    with zipfile.ZipFile(corrupt, "w") as archive:
        for name, blob in entries.items():
            archive.writestr(name, blob)
    try:
        verify_backup(corrupt)
        print("tamper    : NOT DETECTED (should not happen)")
    except BackupError as exc:
        print(f"tamper    : refused — {exc}")


if __name__ == "__main__":
    main()
