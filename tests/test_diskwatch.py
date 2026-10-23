import tempfile
import unittest
from pathlib import Path

from ops.diskwatch import MB, check_usage, dir_size


class DiskWatchTests(unittest.TestCase):
    def test_empty_dir_ok(self):
        data = Path(tempfile.mkdtemp())
        report = check_usage(data)
        self.assertEqual(report.level, "ok")
        self.assertEqual(report.total_bytes, 0)

    def test_size_accumulates(self):
        data = Path(tempfile.mkdtemp())
        (data / "a.bin").write_bytes(b"x" * 5000)
        (data / "sub").mkdir()
        (data / "sub" / "b.bin").write_bytes(b"y" * 3000)
        self.assertEqual(dir_size(data), 8000)

    def test_warn_and_critical_levels(self):
        data = Path(tempfile.mkdtemp())
        (data / "big.bin").write_bytes(b"z" * int(2 * MB))
        report = check_usage(data, warn_mb=1.0, critical_mb=4.0)
        self.assertEqual(report.level, "warn")
        report = check_usage(data, warn_mb=1.0, critical_mb=1.5)
        self.assertEqual(report.level, "critical")

    def test_report_shape(self):
        data = Path(tempfile.mkdtemp())
        payload = check_usage(data, warn_mb=1, critical_mb=2).to_dict()
        for key in ("total_mb", "level", "warn_threshold_mb",
                    "critical_threshold_mb"):
            self.assertIn(key, payload)

    def test_missing_dir_zero(self):
        report = check_usage(Path(tempfile.mkdtemp()) / "nope")
        self.assertEqual(report.total_bytes, 0)


if __name__ == "__main__":
    unittest.main()
