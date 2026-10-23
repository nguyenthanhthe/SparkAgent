import tempfile
import unittest
import zipfile
from pathlib import Path

from ops.backup import BackupError, create_backup, restore_backup, verify_backup


def make_data_dir() -> Path:
    data = Path(tempfile.mkdtemp()) / "data"
    (data / "logs").mkdir(parents=True)
    (data / "sandbox").mkdir()
    (data / "sparkagent.db").write_bytes(b"database-bytes-0123")
    (data / "logs" / "run.log").write_text("log line\n", encoding="utf-8")
    (data / "sandbox" / "note.txt").write_text("hi", encoding="utf-8")
    (data / "vault.bin").write_bytes(b"secret-blob")   # must be excluded
    return data


class BackupTests(unittest.TestCase):
    def test_backup_excludes_vault(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        self.assertEqual(result.file_count, 3)   # db + log + note, no vault
        with zipfile.ZipFile(result.archive_path) as archive:
            names = archive.namelist()
        self.assertFalse(any("vault.bin" in name for name in names))
        self.assertIn("manifest.json", names)

    def test_verify_ok(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        manifest = verify_backup(result.archive_path)
        self.assertEqual(manifest["file_count"], 3)
        self.assertEqual(manifest["digest"], result.digest)

    def test_tampered_archive_detected(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        # rewrite one entry with different content
        with zipfile.ZipFile(result.archive_path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["sandbox/note.txt"] = b"tampered"
        with zipfile.ZipFile(result.archive_path, "w") as archive:
            for name, blob in entries.items():
                archive.writestr(name, blob)
        with self.assertRaises(BackupError) as ctx:
            verify_backup(result.archive_path)
        self.assertIn("corrupted", str(ctx.exception))

    def test_missing_manifest_rejected(self):
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        archive_path = next(output.glob("*.zip"))
        with zipfile.ZipFile(archive_path) as archive:
            entries = {name: archive.read(name)
                       for name in archive.namelist()
                       if name != "manifest.json"}
        with zipfile.ZipFile(archive_path, "w") as archive:
            for name, blob in entries.items():
                archive.writestr(name, blob)
        with self.assertRaises(BackupError):
            verify_backup(archive_path)

    def test_restore_roundtrip(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        target = Path(tempfile.mkdtemp()) / "data"
        restored = restore_backup(result.archive_path, target)
        self.assertEqual(restored["restored_files"], 3)
        self.assertEqual((target / "sandbox" / "note.txt").read_text(), "hi")
        self.assertFalse((target / "vault.bin").exists())

    def test_restore_refuses_nonempty_target(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        target = Path(tempfile.mkdtemp())
        (target / "existing.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(BackupError) as ctx:
            restore_backup(result.archive_path, target)
        self.assertIn("not empty", str(ctx.exception))
        # overwrite succeeds
        restored = restore_backup(result.archive_path, target, overwrite=True)
        self.assertEqual(restored["restored_files"], 3)

    def test_empty_data_dir_rejected(self):
        empty = Path(tempfile.mkdtemp()) / "data"
        empty.mkdir()
        with self.assertRaises(BackupError):
            create_backup(empty, empty.parent / "out")

    def test_missing_archive_rejected(self):
        with self.assertRaises(BackupError):
            verify_backup(Path("no/such/backup.zip"))


if __name__ == "__main__":
    unittest.main()
