import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ops.backup import (BackupError, create_backup, main, prune_backups,
                        restore_backup, verify_backup)


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

    def test_extra_dirs_included(self):
        data = make_data_dir()
        skills = Path(tempfile.mkdtemp()) / "skills"
        skills.mkdir()
        (skills / "alpha.py").write_text("print('a')", encoding="utf-8")
        (skills / "beta.py").write_text("print('b')", encoding="utf-8")
        result = create_backup(data, data.parent / "backups",
                               extra_dirs=[skills])
        self.assertEqual(result.file_count, 5)   # db + log + note + 2 skills
        with zipfile.ZipFile(result.archive_path) as archive:
            names = archive.namelist()
        self.assertIn("skills/alpha.py", names)
        self.assertIn("skills/beta.py", names)

    def test_prune_keeps_newest(self):
        from unittest import mock
        data = make_data_dir()
        output = data.parent / "backups"
        counter = {"n": 0}

        def fake_strftime(fmt, t=None):
            if "T" in fmt:   # manifest created_at
                return "2026-01-01T00:00:00"
            counter["n"] += 1
            return f"20260101-0000{counter['n']:02d}"

        with mock.patch("ops.backup.time.strftime", fake_strftime):
            for _ in range(4):
                create_backup(data, output)
        self.assertEqual(len(list(output.glob("*.zip"))), 4)
        removed = prune_backups(output, keep=2)
        self.assertEqual(removed, 2)
        self.assertEqual(len(list(output.glob("*.zip"))), 2)

    def test_prune_zero_keeps_nothing(self):
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        self.assertEqual(prune_backups(output, keep=0), 1)
        self.assertEqual(list(output.glob("*.zip")), [])

    def test_cli_create_verify(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output), "--keep", "5"])
        self.assertEqual(rc, 0)
        summary = json.loads(buffer.getvalue())
        self.assertEqual(summary["pruned"], 0)
        self.assertTrue(Path(summary["archive"]).exists())

        with contextlib.redirect_stdout(buffer):
            rc = main(["verify", summary["archive"]])
        self.assertEqual(rc, 0)
        verdict = json.loads(buffer.getvalue().splitlines()[-1])
        self.assertTrue(verdict["ok"])


if __name__ == "__main__":
    unittest.main()
