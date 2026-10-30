import tempfile
import time
import unittest
from pathlib import Path

from security.quarantine import QuarantineStore


class QuarantineTTLTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store = QuarantineStore(self.root, ttl_seconds=3600)

    def test_recent_items_survive_sweep(self):
        self.store.put("fresh content", "test")
        self.assertEqual(self.store.expire(), 0)
        self.assertEqual(len(self.store.list()), 1)

    def test_old_items_removed(self):
        record = self.store.put("stale content", "test")
        # backdate the record's created_at beyond the TTL
        meta = self.root / f"{record['id']}.json"
        import json
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["created_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.store.expire(), 1)
        self.assertEqual(self.store.list(), [])

    def test_zero_ttl_disables_sweep(self):
        store = QuarantineStore(self.root, ttl_seconds=0)
        record = store.put("kept", "test")
        import json
        meta = self.root / f"{record['id']}.json"
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["created_at"] = "1999-01-01T00:00:00"
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(store.expire(), 0)
        self.assertEqual(len(store.list()), 1)

    def test_unparsable_timestamp_kept(self):
        self.store.put("mystery", "test")
        import json
        meta_path = next(self.root.glob("*.json"))
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["created_at"] = "not-a-timestamp"
        meta_path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.store.expire(), 0)
        self.assertEqual(len(self.store.list()), 1)


class QuarantineStatsTests(unittest.TestCase):
    def test_stats_reports_items_bytes_age(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        store.put("body one", "r1")
        stats = store.stats()
        self.assertEqual(stats["items"], 1)
        self.assertEqual(stats["bytes"], len(b"body one"))
        self.assertGreaterEqual(stats["oldest_age_s"], 0)
        # human form rides alongside: seconds-old shows as NmNNs
        import re
        self.assertRegex(stats["oldest_human"], r"^\d+m\d{2}s$")

    def test_stats_oldest_human_hours_form(self):
        import os
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        store.put("aged body", "r1")
        # backdate the record by 3 hours so the human form flips to NhMMm
        meta_path = next(store.root.glob("*.json"))
        import json
        record = json.loads(meta_path.read_text(encoding="utf-8"))
        record["created_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3 * 3600))
        meta_path.write_text(json.dumps(record), encoding="utf-8")
        os.utime(meta_path)
        stats = store.stats()
        self.assertRegex(stats["oldest_human"], r"^3h\d{2}m$")

    def test_stats_top_reasons(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        for _ in range(3):
            store.put("a", "prompt-injection risk")
        store.put("b", "oversized skill proposal")
        top = store.stats()["top_reasons"]
        self.assertEqual(top, {"prompt-injection": 3,
                               "oversized": 1})

    def test_put_rejects_blank_content(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            store.put("", "reason")
        with self.assertRaises(ValueError):
            store.put("   \n", "reason")

    def test_empty_store_stats(self):
        stats = QuarantineStore(Path(tempfile.mkdtemp())).stats()
        self.assertEqual(stats["items"], 0)
        self.assertEqual(stats["bytes"], 0)
        self.assertIsNone(stats["oldest_age_s"])
        self.assertIsNone(stats["oldest_human"])
        self.assertEqual(stats["top_reasons"], {})


if __name__ == "__main__":
    unittest.main()
