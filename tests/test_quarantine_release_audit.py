"""Quarantine release audits the content LENGTH, never the content."""

import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from security.quarantine import QuarantineStore


class ReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "quarantine"
        self.bus = EventBus()
        self.queue = self.bus.subscribe("audit")
        self.store = QuarantineStore(self.root, bus=self.bus)

    def _drain(self) -> list[dict]:
        events = []
        while not self.queue.empty():
            events.append(self.queue.get_nowait())
        return events

    def test_release_publishes_length_only(self):
        content = "secret payload body"
        record = self.store.put(content, reason="test flag")
        self.store.release(record["id"])

        events = self._drain()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["actor"], "system")
        self.assertEqual(event["action"], "quarantine.release")
        detail = event["detail"]
        self.assertEqual(detail["item_id"], record["id"])
        self.assertEqual(detail["length"], len(content))
        # the content itself must not travel to the audit log
        import json
        self.assertNotIn(content, json.dumps(event))

    def test_release_without_bus_still_works(self):
        bare = QuarantineStore(Path(tempfile.mkdtemp()) / "q")
        record = bare.put("another payload", reason="test flag")
        self.assertEqual(bare.release(record["id"]), "another payload")
        self.assertFalse((bare.root / f"{record['id']}.json").exists())

    def test_release_length_reflects_sanitized_content(self):
        record = self.store.put("clean body", reason="test flag")
        released = self.store.release(record["id"])
        detail = self._drain()[0]["detail"]
        self.assertEqual(detail["length"], len(released))


if __name__ == "__main__":
    unittest.main()
