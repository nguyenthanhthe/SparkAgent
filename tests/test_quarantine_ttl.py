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


if __name__ == "__main__":
    unittest.main()
