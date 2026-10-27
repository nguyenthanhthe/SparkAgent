"""Backup and restore for the SparkAgent data directory.

Creates a compressed archive of ``data/`` (SQLite database, logs,
sandbox, quarantine) with a JSON manifest: file list, sizes, SHA-256 per
file, and a digest of the whole set. Restore verifies every hash before
writing a single byte — a corrupted or tampered backup never reaches the
live directory. Secrets (``vault.bin``) are excluded by default: backups
should not carry master-key-encrypted blobs to machines without the key.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "manifest.json"
DEFAULT_EXCLUDES = {"vault.bin", "*.log.*"}

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


class BackupError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class BackupResult:
    archive_path: Path
    file_count: int
    total_bytes: int
    digest: str


def _iter_files(data_dir: Path, excludes: set[str]) -> list[Path]:
    files = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(data_dir).as_posix()
        if any(Path(relative).match(pattern) or
               Path(path.name).match(pattern) for pattern in excludes):
            continue
        files.append(path)
    return files


def create_backup(data_dir: Path, output_dir: Path,
                  excludes: set[str] | None = None,
                  extra_dirs: list[Path] | None = None,
                  tag: str | None = None) -> BackupResult:
    """Zip ``data_dir`` (minus excludes) plus any ``extra_dirs`` (e.g.
    skills/) into a verified archive. Extra files are stored under their
    directory name, so restore lands them inside the data dir."""
    if not data_dir.is_dir():
        raise BackupError(f"data directory not found: {data_dir}")
    excludes = excludes or DEFAULT_EXCLUDES
    entries_src: list[tuple[Path, str]] = [
        (path, path.relative_to(data_dir).as_posix())
        for path in _iter_files(data_dir, excludes)]
    for extra in (extra_dirs or []):
        if not extra.is_dir():
            continue
        entries_src.extend(
            (path, f"{extra.name}/{path.relative_to(extra).as_posix()}")
            for path in _iter_files(extra, excludes))
    if not entries_src:
        raise BackupError("nothing to back up")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"sparkagent-backup-{stamp}.zip"

    entries = []
    total = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in entries_src:
            size = path.stat().st_size
            total += size
            if total > MAX_ARCHIVE_BYTES:
                archive_path.unlink(missing_ok=True)
                raise BackupError("backup exceeds size limit")
            archive.write(path, arcname)
            entries.append({"path": arcname, "bytes": size,
                            "sha256": _sha256(path)})
    combined = hashlib.sha256(
        "\n".join(f"{e['path']}:{e['sha256']}" for e in entries)
        .encode()).hexdigest()
    manifest = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "version": 1, "file_count": len(entries),
                "total_bytes": total, "digest": combined, "files": entries}
    if tag:
        manifest["tag"] = str(tag)[:100]
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=1))
    return BackupResult(archive_path=archive_path, file_count=len(entries),
                        total_bytes=total, digest=combined)


def verify_backup(archive_path: Path) -> dict:
    """Check manifest presence and per-file hashes; return the manifest."""
    if not archive_path.is_file():
        raise BackupError(f"archive not found: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if MANIFEST_NAME not in names:
            raise BackupError("archive has no manifest — not a SparkAgent "
                              "backup")
        manifest = json.loads(archive.read(MANIFEST_NAME))
        for entry in manifest.get("files", []):
            if entry["path"] not in names:
                raise BackupError(f"missing file in archive: {entry['path']}")
            actual = hashlib.sha256(archive.read(entry["path"])).hexdigest()
            if actual != entry["sha256"]:
                raise BackupError(
                    f"hash mismatch for {entry['path']}: backup corrupted")
        combined = hashlib.sha256(
            "\n".join(f"{e['path']}:{e['sha256']}"
                      for e in manifest.get("files", []))
            .encode()).hexdigest()
        if combined != manifest.get("digest"):
            raise BackupError("manifest digest mismatch — tampered backup")
    return manifest


def prune_backups(output_dir: Path, keep: int = 10,
                  dry_run: bool = False) -> int:
    """Delete the oldest backup archives beyond ``keep``; returns how
    many were (or with ``dry_run``, would be) removed. ``keep <= 0``
    removes everything."""
    archives = sorted(output_dir.glob("sparkagent-backup-*.zip"))
    doomed = archives[:-keep] if keep > 0 else archives
    if dry_run:
        return len(doomed)
    removed = 0
    for path in doomed:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def restore_backup(archive_path: Path, data_dir: Path,
                   overwrite: bool = False) -> dict:
    """Verify-then-restore. Writes only after all hashes check out."""
    manifest = verify_backup(archive_path)
    if data_dir.exists() and any(data_dir.iterdir()) and not overwrite:
        raise BackupError(f"{data_dir} is not empty — pass overwrite=True")
    if data_dir.exists():
        shutil.rmtree(data_dir)
    with zipfile.ZipFile(archive_path) as archive:
        for entry in manifest["files"]:
            target = data_dir / entry["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry["path"]))
    return {"restored_files": manifest["file_count"],
            "total_bytes": manifest["total_bytes"]}


def restore_drill(archive_path: Path, work_dir: Path | None = None) -> dict:
    """Restore drill: verify, then restore into a throwaway scratch
    directory and remove it. Never touches the live data dir — run this
    periodically; a backup you have never restored is a hope, not a
    backup."""
    manifest = verify_backup(archive_path)
    scratch = Path(work_dir or Path(tempfile.mkdtemp())) / \
        f"sparkagent-drill-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        outcome = restore_backup(archive_path, scratch, overwrite=False)
        restored_bytes = sum(
            (scratch / entry["path"]).stat().st_size
            for entry in manifest["files"])
        byte_ok = restored_bytes == manifest["total_bytes"]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"ok": byte_ok, "files": outcome["restored_files"],
            "bytes": manifest["total_bytes"],
            "tag": manifest.get("tag")}


def list_backups(backup_dir: Path, limit: int = 20) -> dict:
    """Backup-window listing: name, age, size, manifest tag per archive,
    newest first. Listing is best-effort (a corrupt archive shows with
    no tag) — hash verification stays in verify_backup/verify-all."""
    archives = []
    for path in sorted(backup_dir.glob("sparkagent-backup-*.zip"),
                       reverse=True):
        entry = {"name": path.name,
                 "age_s": round(time.time() - path.stat().st_mtime),
                 "bytes": path.stat().st_size, "tag": None}
        try:
            with zipfile.ZipFile(path) as archive:
                if MANIFEST_NAME in archive.namelist():
                    entry["tag"] = json.loads(
                        archive.read(MANIFEST_NAME)).get("tag")
        except (OSError, zipfile.BadZipFile, ValueError):
            pass
        archives.append(entry)
    return {"dir": str(backup_dir), "archives": archives[:limit]}


def _verify_all(output_dir: Path) -> int:
    """Verify every archive in the retention window; exit 1 if any fails."""
    archives = sorted(output_dir.glob("sparkagent-backup-*.zip"))
    if not archives:
        print(json.dumps({"ok": False, "error": "no backups found",
                          "dir": str(output_dir)}))
        return 1
    results = []
    for archive in archives:
        try:
            manifest = verify_backup(archive)
            results.append({"archive": archive.name, "ok": True,
                            "files": manifest["file_count"],
                            "tag": manifest.get("tag")})
        except BackupError as exc:
            results.append({"archive": archive.name, "ok": False,
                            "error": str(exc)[:200]})
    ok = all(item["ok"] for item in results)
    print(json.dumps({"ok": ok, "count": len(results),
                      "archives": results}))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    """CLI: python -m ops.backup create|verify|restore."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m ops.backup",
        description="SparkAgent backup tool (db + skills, with retention)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create", help="create and prune backups")
    p_create.add_argument("--data-dir", required=True)
    p_create.add_argument("--skills-dir", default=None,
                          help="optional extra directory (e.g. skills/)")
    p_create.add_argument("--output-dir", required=True)
    p_create.add_argument("--keep", type=int, default=10)
    p_create.add_argument("--tag", default=None,
                          help="optional label stored in the manifest "
                               "(e.g. 'pre-upgrade')")
    p_verify = sub.add_parser("verify", help="verify an archive")
    p_verify.add_argument("archive")
    p_verify_all = sub.add_parser("verify-all",
                                  help="verify every archive in the "
                                       "backup dir")
    p_verify_all.add_argument("--output-dir", required=True)
    p_prune = sub.add_parser("prune", help="apply retention to the dir")
    p_prune.add_argument("--output-dir", required=True)
    p_prune.add_argument("--keep", type=int, default=10)
    p_prune.add_argument("--dry-run", action="store_true",
                         help="report what would be removed, delete "
                              "nothing")
    p_restore = sub.add_parser("restore", help="verify then restore")
    p_restore.add_argument("archive")
    p_restore.add_argument("--data-dir", required=True)
    p_restore.add_argument("--overwrite", action="store_true")
    p_drill = sub.add_parser(
        "drill", help="verify + restore into a scratch dir (never the "
                      "live one), then clean up")
    p_drill.add_argument("archive")
    p_drill.add_argument("--work-dir", default=None,
                         help="parent for the scratch dir (default: temp)")
    args = parser.parse_args(argv)

    if args.cmd == "create":
        extra = [Path(args.skills_dir)] if args.skills_dir else None
        result = create_backup(Path(args.data_dir), Path(args.output_dir),
                               extra_dirs=extra, tag=args.tag)
        pruned = prune_backups(Path(args.output_dir), keep=args.keep)
        print(json.dumps({"archive": str(result.archive_path),
                          "files": result.file_count,
                          "bytes": result.total_bytes,
                          "digest": result.digest,
                          "tag": args.tag,
                          "pruned": pruned}))
        return 0
    if args.cmd == "verify":
        manifest = verify_backup(Path(args.archive))
        print(json.dumps({"ok": True, "files": manifest["file_count"],
                          "digest": manifest["digest"],
                          "tag": manifest.get("tag")}))
        return 0
    if args.cmd == "verify-all":
        return _verify_all(Path(args.output_dir))
    if args.cmd == "prune":
        removed = prune_backups(Path(args.output_dir), keep=args.keep,
                                dry_run=args.dry_run)
        print(json.dumps({"removed": removed, "keep": args.keep,
                          "dry_run": args.dry_run}))
        return 0
    if args.cmd == "drill":
        try:
            result = restore_drill(Path(args.archive),
                                   work_dir=Path(args.work_dir)
                                   if args.work_dir else None)
        except BackupError as exc:
            print(json.dumps({"ok": False, "error": str(exc)[:200]}))
            return 1
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    result = restore_backup(Path(args.archive), Path(args.data_dir),
                            overwrite=args.overwrite)
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
