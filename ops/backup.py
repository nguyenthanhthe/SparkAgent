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
                  excludes: set[str] | None = None) -> BackupResult:
    """Zip ``data_dir`` (minus excludes) into a verified archive."""
    if not data_dir.is_dir():
        raise BackupError(f"data directory not found: {data_dir}")
    excludes = excludes or DEFAULT_EXCLUDES
    files = _iter_files(data_dir, excludes)
    if not files:
        raise BackupError("nothing to back up")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"sparkagent-backup-{stamp}.zip"

    entries = []
    total = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(data_dir).as_posix()
            size = path.stat().st_size
            total += size
            if total > MAX_ARCHIVE_BYTES:
                archive_path.unlink(missing_ok=True)
                raise BackupError("backup exceeds size limit")
            archive.write(path, relative)
            entries.append({"path": relative, "bytes": size,
                            "sha256": _sha256(path)})
    combined = hashlib.sha256(
        "\n".join(f"{e['path']}:{e['sha256']}" for e in entries)
        .encode()).hexdigest()
    manifest = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "version": 1, "file_count": len(entries),
                "total_bytes": total, "digest": combined, "files": entries}
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
