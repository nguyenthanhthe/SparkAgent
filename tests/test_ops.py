import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ops.backup import (BackupError, create_backup, main, prune_backups,
                        restore_backup, restore_drill, verify_backup)

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

    def test_cli_verify_reports_byte_size(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        created = create_backup(data, output)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify", str(created.archive_path)])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertEqual(report["bytes"],
                         created.archive_path.stat().st_size)
        self.assertGreater(report["bytes"], 0)

    def test_cli_verify_corrupt_archive_is_machine_readable(self):
        import contextlib
        import io
        import json
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        corrupt = output / "sparkagent-backup-00000000-000000.zip"
        with zipfile.ZipFile(corrupt, "w") as archive:
            archive.writestr("blob.txt", "not a sparkagent backup")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify", str(corrupt)])
        self.assertEqual(rc, 1)
        payload = json.loads(buffer.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("manifest", payload["error"].lower())

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

    def test_prune_dry_run_deletes_nothing(self):
        data = make_data_dir()
        output = data.parent / "backups"
        for name in ("sparkagent-backup-20260101-000001.zip",
                     "sparkagent-backup-20260101-000002.zip",
                     "sparkagent-backup-20260101-000003.zip"):
            (output).mkdir(exist_ok=True)
            (output / name).write_bytes(b"stub")
        would = prune_backups(output, keep=1, dry_run=True)
        self.assertEqual(would, 2)
        self.assertEqual(len(list(output.glob("*.zip"))), 3)
        removed = prune_backups(output, keep=1)
        self.assertEqual(removed, 2)
        self.assertEqual(len(list(output.glob("*.zip"))), 1)

    def test_cli_verify_all_tag_filter(self):
        import contextlib
        import io
        import shutil
        from unittest import mock
        data = make_data_dir()
        output = data.parent / "backups"
        counter = {"n": 0}

        def fake_strftime(fmt, t=None):
            if "T" in fmt:
                return "2026-01-01T00:00:00"
            counter["n"] += 1
            return f"20260101-0000{counter['n']:02d}"

        with mock.patch("ops.backup.time.strftime", fake_strftime):
            create_backup(data, output, tag="nightly")
            create_backup(data, output, tag="weekly")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output),
                       "--tag", "nightly"])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["archives"][0]["tag"], "nightly")
        # no match -> honest failure exit with the tag echoed
        buffer2 = io.StringIO()
        with contextlib.redirect_stdout(buffer2):
            rc = main(["verify-all", "--output-dir", str(output),
                       "--tag", "never"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(buffer2.getvalue())["tag"], "never")

    def test_cli_prune_audits_removals(self):
        import contextlib
        import io
        import sqlite3
        data = make_data_dir()
        (data / "sparkagent.db").unlink()
        conn = sqlite3.connect(data / "sparkagent.db")
        conn.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY "
                     "AUTOINCREMENT, created_at TEXT NOT NULL, "
                     "actor TEXT NOT NULL, action TEXT NOT NULL, "
                     "detail TEXT)")
        conn.commit()
        conn.close()
        output = data.parent / "backups"
        for name in ("sparkagent-backup-20260101-000001.zip",
                     "sparkagent-backup-20260101-000002.zip",
                     "sparkagent-backup-20260101-000003.zip"):
            output.mkdir(exist_ok=True)
            (output / name).write_bytes(b"stub")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["prune", "--output-dir", str(output), "--keep", "1",
                       "--data-dir", str(data)])
        self.assertEqual(rc, 0)
        conn = sqlite3.connect(data / "sparkagent.db")
        try:
            row = conn.execute("SELECT detail FROM audit "
                               "WHERE action = 'backup.prune'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertIn("removed=2", row[0])

    def test_cli_prune_dry_run(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        output.mkdir(exist_ok=True)
        for name in ("sparkagent-backup-20260101-000001.zip",
                     "sparkagent-backup-20260101-000002.zip"):
            (output / name).write_bytes(b"stub")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["prune", "--output-dir", str(output),
                       "--keep", "1", "--dry-run"])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["removed"], 1)
        self.assertEqual(report["would_remain"], 1)
        self.assertEqual(len(list(output.glob("*.zip"))), 2)

    def test_cli_verify_all_quiet(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output),
                       "--quiet"])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["ok"])
        self.assertIn("T", report["checked_at"])

    def test_cli_verify_all_quiet_slowest(self):
        import contextlib
        import io
        import shutil
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        original = next(output.glob("sparkagent-backup-*.zip"))
        shutil.copyfile(original,
                        output / "sparkagent-backup-20980101-000000.zip")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output),
                       "--quiet"])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue().splitlines()[-1])
        self.assertTrue(report["ok"])
        self.assertEqual(report["count"], 2)
        self.assertEqual(report["failed"], [])
        self.assertEqual(report["slowest"]["archive"],
                         Path(report["slowest"]["archive"]).name)
        self.assertGreaterEqual(report["slowest"]["seconds"], 0)
        self.assertNotIn("archives", report)

    def test_cli_verify_all_reports_duration(self):
        import contextlib
        import io
        import shutil
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        original = next(output.glob("sparkagent-backup-*.zip"))
        shutil.copyfile(original,
                        output / "sparkagent-backup-20980101-000000.zip")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output)])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue().splitlines()[-1])
        for item in report["archives"]:
            self.assertGreaterEqual(item["seconds"], 0)

    def test_prune_zero_keeps_nothing(self):
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        self.assertEqual(prune_backups(output, keep=0), 1)
        self.assertEqual(list(output.glob("*.zip")), [])

    def test_cli_create_verify_immediately(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output),
                       "--verify-immediately"])
        self.assertEqual(rc, 0)
        summary = json.loads(buffer.getvalue())
        self.assertTrue(summary["verified"])
        # without the flag the field says so honestly
        output2 = data.parent / "backups2"
        buffer2 = io.StringIO()
        with contextlib.redirect_stdout(buffer2):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output2)])
        self.assertEqual(rc, 0)
        self.assertFalse(json.loads(buffer2.getvalue())["verified"])

    def test_cli_create_verify(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output),
                       "--verify-immediately"])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["verified"])

    def test_cli_create_retention_position(self):
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
        self.assertEqual(summary["retention"], "1 of 5")
        self.assertTrue(Path(summary["archive"]).exists())

        with contextlib.redirect_stdout(buffer):
            rc = main(["verify", summary["archive"]])
        self.assertEqual(rc, 0)
        verdict = json.loads(buffer.getvalue().splitlines()[-1])
        self.assertTrue(verdict["ok"])

    def test_cli_create_audits_into_db(self):
        import contextlib
        import io
        import sqlite3
        data = make_data_dir()
        # the stub db is not a real sqlite file — make it one with the
        # audit table, as the daemon would have
        (data / "sparkagent.db").unlink()
        conn = sqlite3.connect(data / "sparkagent.db")
        conn.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY "
                     "AUTOINCREMENT, created_at TEXT NOT NULL, "
                     "actor TEXT NOT NULL, action TEXT NOT NULL, "
                     "detail TEXT)")
        conn.commit()
        conn.close()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output)])
        self.assertEqual(rc, 0)
        conn = sqlite3.connect(data / "sparkagent.db")
        try:
            row = conn.execute(
                "SELECT actor, action, detail FROM audit "
                "WHERE action = 'backup.create'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "ops.backup")
        self.assertIn("files=3", row[2])

    def test_cli_create_with_stub_db_still_succeeds(self):
        # the stub db is not sqlite — the audit write is best-effort
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output)])
        self.assertEqual(rc, 0)

    def test_cli_drill_audits_into_db(self):
        import contextlib
        import io
        import sqlite3
        data = make_data_dir()
        (data / "sparkagent.db").unlink()
        conn = sqlite3.connect(data / "sparkagent.db")
        conn.execute("CREATE TABLE audit (id INTEGER PRIMARY KEY "
                     "AUTOINCREMENT, created_at TEXT NOT NULL, "
                     "actor TEXT NOT NULL, action TEXT NOT NULL, "
                     "detail TEXT)")
        conn.commit()
        conn.close()
        output = data.parent / "backups"
        created = create_backup(data, output, tag="drill")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["drill", str(created.archive_path),
                       "--data-dir", str(data)])
        self.assertEqual(rc, 0)
        conn = sqlite3.connect(data / "sparkagent.db")
        try:
            row = conn.execute(
                "SELECT detail FROM audit "
                "WHERE action = 'backup.drill'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertIn("ok=True", row[0])

    def test_restore_drill_roundtrip_in_scratch(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups", tag="drill")
        summary = restore_drill(result.archive_path)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["files"], 3)
        self.assertEqual(summary["tag"], "drill")
        # the summary names the archive it exercised
        self.assertEqual(summary["archive"], str(result.archive_path))
        # live data dir untouched, scratch dir gone
        self.assertEqual((data / "sparkagent.db").read_bytes(),
                         b"database-bytes-0123")

    def test_restore_drill_verbose_reports_scratch(self):
        import contextlib
        import io
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            summary = restore_drill(result.archive_path, verbose=True)
        self.assertIn("drill scratch:", buffer.getvalue())
        self.assertTrue(summary["ok"])

    def test_restore_drill_refuses_corrupt_archive(self):
        data = make_data_dir()
        result = create_backup(data, data.parent / "backups")
        with zipfile.ZipFile(result.archive_path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["sandbox/note.txt"] = b"tampered"
        corrupt = data.parent / "corrupt.zip"
        with zipfile.ZipFile(corrupt, "w") as archive:
            for name, blob in entries.items():
                archive.writestr(name, blob)
        with self.assertRaises(BackupError):
            restore_drill(corrupt)

    def test_cli_drill(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        created = create_backup(data, output)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["drill", str(created.archive_path)])
        self.assertEqual(rc, 0)
        summary = json.loads(buffer.getvalue().splitlines()[-1])
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["files"], 3)

    def test_tag_label_in_manifest_and_verify(self):
        data = make_data_dir()
        output = data.parent / "backups"
        result = create_backup(data, output, tag="pre-upgrade")
        manifest = verify_backup(result.archive_path)
        self.assertEqual(manifest["tag"], "pre-upgrade")
        untagged = create_backup(data, output)
        self.assertIsNone(verify_backup(untagged.archive_path).get("tag"))

    def test_cli_create_tag_summary_matches_manifest(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        long_tag = "t" * 150
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output), "--tag", long_tag])
        self.assertEqual(rc, 0)
        report = json.loads(buffer.getvalue())
        # the summary shows the SAME truncated tag the manifest stores
        self.assertEqual(report["tag"], "t" * 100)
        self.assertEqual(verify_backup(Path(report["archive"]))["tag"],
                         report["tag"])

    def test_blank_tag_rejected(self):
        data = make_data_dir()
        output = data.parent / "backups"
        for bad in ("", "   ", "\t\n"):
            with self.assertRaises(BackupError):
                create_backup(data, output, tag=bad)
        # a whitespace-padded tag is trimmed, not rejected
        result = create_backup(data, output, tag="  nightly  ")
        self.assertEqual(verify_backup(result.archive_path)["tag"],
                         "nightly")

    def test_cli_tag_surfaces_in_verify_and_verify_all(self):
        import contextlib
        import io
        import shutil
        data = make_data_dir()
        output = data.parent / "backups"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["create", "--data-dir", str(data),
                       "--output-dir", str(output), "--tag", "pre-migration"])
        self.assertEqual(rc, 0)
        archive = json.loads(buffer.getvalue())["archive"]

        with contextlib.redirect_stdout(buffer):
            rc = main(["verify", archive])
        verdict = json.loads(buffer.getvalue().splitlines()[-1])
        self.assertEqual(verdict["tag"], "pre-migration")

        shutil.copyfile(Path(archive),
                        output / "sparkagent-backup-20980101-000000.zip")
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output)])
        report = json.loads(buffer.getvalue().splitlines()[-1])
        tags = {item["tag"] for item in report["archives"]}
        self.assertEqual(tags, {"pre-migration"})

    def test_cli_verify_all(self):
        import contextlib
        import io
        import shutil
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        # same-second creates collide on the timestamped name; copy one
        # to an older name so the window holds two archives
        original = next(output.glob("sparkagent-backup-*.zip"))
        shutil.copyfile(original,
                        output / "sparkagent-backup-20980101-000000.zip")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output)])
        self.assertEqual(rc, 0)
        verdict = json.loads(buffer.getvalue())
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["count"], 2)
        self.assertTrue(all(a["ok"] for a in verdict["archives"]))

    def test_cli_verify_all_flags_corruption(self):
        import contextlib
        import io
        data = make_data_dir()
        output = data.parent / "backups"
        create_backup(data, output)
        corrupt = output / "sparkagent-backup-20990101-0000.zip"
        with zipfile.ZipFile(corrupt, "w") as archive:
            archive.writestr("garbage.txt", "not a backup")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output)])
        self.assertEqual(rc, 1)
        verdict = json.loads(buffer.getvalue())
        self.assertFalse(verdict["ok"])
        by_name = {a["archive"]: a for a in verdict["archives"]}
        self.assertFalse(by_name[corrupt.name]["ok"])

    def test_cli_verify_all_empty_dir(self):
        import contextlib
        import io
        output = Path(tempfile.mkdtemp()) / "backups"
        output.mkdir()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = main(["verify-all", "--output-dir", str(output)])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(buffer.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
