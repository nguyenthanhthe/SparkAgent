import json
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

    def test_sweep_is_audited_with_counts(self):
        from kernel.bus import EventBus
        bus = EventBus()
        queue = bus.subscribe("audit")
        store = QuarantineStore(self.root, ttl_seconds=3600, bus=bus)
        record = store.put("stale content", "test")
        meta = self.root / f"{record['id']}.json"
        import json
        data = json.loads(meta.read_text(encoding="utf-8"))
        data["created_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(store.expire(), 1)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["action"], "quarantine.expire")
        self.assertEqual(events[0]["detail"], {"removed": 1})
        # a sweep that removes nothing publishes nothing
        self.assertEqual(store.expire(), 0)
        self.assertTrue(queue.empty())

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

    def test_list_rows_carry_age_human(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        store.put("body", "reason")
        row = store.list()[0]
        import re
        self.assertRegex(row["age_human"], r"^\d+m\d{2}s$")

    def test_meta_dict_is_capped(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        big_meta = {f"key_{i}": "v" * 500 for i in range(30)}
        record = store.put("body", "reason", big_meta)
        self.assertLessEqual(
            len(json.dumps(record["meta"])), 2048 + 200)
        self.assertLessEqual(len(record["meta"]), 10)
        # typed values survive the cap
        typed = store.put("body", "reason", {"score": 70})
        self.assertEqual(typed["meta"]["score"], 70)

    def test_get_exposes_human_age(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        record = store.put("body", "reason")
        got = store.get(record["id"])
        import re
        self.assertRegex(got["age_human"], r"^\d+m\d{2}s$")
        # unknown ids still raise
        with self.assertRaises(KeyError):
            store.get("nope")

    def test_put_rejects_blank_reason(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        for bad in ("", "   ", "\t"):
            with self.assertRaises(ValueError):
                store.put("body", bad)

    def test_put_carries_source_label(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        record = store.put("body", "reason", source="web_fetch")
        self.assertEqual(record["source"], "web_fetch")
        # default keeps the field present but honest
        bare = store.put("body", "reason")
        self.assertEqual(bare["source"], "unknown")
        # the label survives the round-trip through list()
        store2 = QuarantineStore(Path(tempfile.mkdtemp()))
        store2.put("body", "reason", source="telegram")
        self.assertEqual(store2.list()[0]["source"], "telegram")

    def test_empty_store_stats(self):
        stats = QuarantineStore(Path(tempfile.mkdtemp())).stats()
        self.assertEqual(stats["items"], 0)
        self.assertEqual(stats["bytes"], 0)
        self.assertIsNone(stats["oldest_age_s"])
        self.assertIsNone(stats["oldest_human"])
        self.assertEqual(stats["top_reasons"], {})

    def test_stats_source_breakdown(self):
        store = QuarantineStore(Path(tempfile.mkdtemp()))
        store.put("a" * 100, "r1", source="web_fetch")
        store.put("b" * 50, "r2", source="web_fetch")
        store.put("c", "r3")   # default label
        stats = store.stats()
        self.assertEqual(stats["by_source"], {"web_fetch": 2,
                                              "unknown": 1})
        # bytes split by the same key, summing to the total
        self.assertEqual(stats["bytes_by_source"]["web_fetch"], 150)
        self.assertEqual(stats["bytes_by_source"]["unknown"], 1)
        self.assertEqual(sum(stats["bytes_by_source"].values()),
                         stats["bytes"])
        # legacy records without a source roll up as unknown
        import json
        legacy = QuarantineStore(Path(tempfile.mkdtemp()))
        record = legacy.put("x", "r")
        meta = next(legacy.root.glob("*.json"))
        data = json.loads(meta.read_text(encoding="utf-8"))
        del data["source"]
        meta.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(legacy.stats()["by_source"], {"unknown": 1})


if __name__ == "__main__":
    unittest.main()
