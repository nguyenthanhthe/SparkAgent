"""diskwatch CLI — exit codes, JSON output, threshold validation."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ops.diskwatch import UsageReport, main


def run_main(*argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


class DiskwatchCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "data").mkdir()
        (self.tmp / "data" / "blob.bin").write_bytes(b"x" * 2048)

    def test_ok_exit_and_report(self):
        code, out = run_main("--data-dir", str(self.tmp / "data"),
                             "--warn-mb", "10", "--critical-mb", "20")
        self.assertEqual(code, 0)
        self.assertIn("level    : ok", out)
        self.assertIn("0.0 MB", out)

    def test_warn_exit_code(self):
        code, out = run_main("--data-dir", str(self.tmp / "data"),
                             "--warn-mb", "0", "--critical-mb", "10")
        self.assertEqual(code, 1)
        self.assertIn("level    : warn", out)

    def test_critical_exit_code(self):
        code, out = run_main("--data-dir", str(self.tmp / "data"),
                             "--warn-mb", "0", "--critical-mb", "0")
        self.assertEqual(code, 2)
        self.assertIn("level    : critical", out)

    def test_critical_prints_tip(self):
        data = self.tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "blob").write_bytes(b"x" * 1024)
        code, out = run_main("--data-dir", str(data),
                             "--warn-mb", "0", "--critical-mb", "0.0001")
        self.assertEqual(code, 2)
        self.assertIn("tip", out)

    def test_json_output(self):
        code, out = run_main("--data-dir", str(self.tmp / "data"),
                             "--json")
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertEqual(body["level"], "ok")
        self.assertIn("total_mb", body)

    def test_missing_data_dir_is_error(self):
        code, out = run_main("--data-dir", str(self.tmp / "nope"))
        self.assertEqual(code, 3)

    def test_critical_below_warn_is_error(self):
        code, _ = run_main("--data-dir", str(self.tmp / "data"),
                           "--warn-mb", "10", "--critical-mb", "5")
        self.assertEqual(code, 3)

    def test_report_level_boundaries(self):
        report = UsageReport(total_bytes=0, warn_threshold_mb=1.0,
                             critical_threshold_mb=2.0)
        self.assertEqual(report.level, "ok")
        self.assertEqual(report.to_dict()["level"], "ok")

    def test_subdirs_top_breakdown(self):
        import json
        from ops.diskwatch import subdirs_top
        data = self.tmp / "data"
        (data / "logs").mkdir(parents=True)
        (data / "logs" / "big.log").write_bytes(b"x" * 5000)
        (data / "quarantine").mkdir()
        (data / "quarantine" / "blob.dat").write_bytes(b"x" * 2000)
        top = subdirs_top(data)
        self.assertEqual([item["dir"] for item in top],
                         ["logs", "quarantine"])
        # the --json payload carries the breakdown
        code, out = run_main("--data-dir", str(data), "--json")
        self.assertEqual(code, 0)
        body = json.loads(out)
        self.assertEqual([item["dir"] for item in body["subdirs_top"]],
                         ["logs", "quarantine"])

    def test_warn_level_names_the_prune_target(self):
        data = self.tmp / "data"
        (data / "logs").mkdir(parents=True)
        (data / "logs" / "big.log").write_bytes(b"x" * 6000)
        code, out = run_main("--data-dir", str(data),
                             "--warn-mb", "0.004")
        self.assertEqual(code, 1)
        self.assertIn("prune target — logs", out)

    def test_all_flag_lists_every_subdir(self):
        from ops.diskwatch import subdirs_top
        data = self.tmp / "data"
        for name in ("a", "b", "c", "d"):
            (data / name).mkdir(parents=True)
            (data / name / "f.bin").write_bytes(b"x")
        self.assertEqual(len(subdirs_top(data)), 3)       # default cap
        self.assertEqual(len(subdirs_top(data, keep=None)), 4)


if __name__ == "__main__":
    unittest.main()
