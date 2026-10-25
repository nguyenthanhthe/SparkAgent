"""Cache hit counting per entry + top_hits digests in /api/brain."""

import unittest

from brain.cache import ResponseCache
from kernel.clock import Clock


class FakeClock(Clock):
    def __init__(self):
        self.t = 1000.0

    def now(self) -> float:
        return self.t


class TopHitsTests(unittest.TestCase):
    def test_hits_counted_per_entry(self):
        clock = FakeClock()
        cache = ResponseCache(max_entries=10, ttl_seconds=100, clock=clock)
        cache.put("k1", "answer one")
        cache.put("k2", "answer two")
        self.assertIsNotNone(cache.get("k1"))
        self.assertIsNotNone(cache.get("k1"))
        self.assertIsNotNone(cache.get("k2"))
        top = cache.top_hits()
        self.assertEqual(top[0]["hits"], 2)
        self.assertEqual(top[1]["hits"], 1)
        self.assertEqual(len(top), 2)

    def test_zero_hit_entries_excluded(self):
        cache = ResponseCache(max_entries=10, ttl_seconds=100,
                              clock=FakeClock())
        cache.put("k1", "never read")
        self.assertEqual(cache.top_hits(), [])

    def test_key_hashes_never_expose_messages(self):
        cache = ResponseCache(max_entries=10, ttl_seconds=100,
                              clock=FakeClock())
        cache.put("secret-prompt-key", "answer")
        cache.get("secret-prompt-key")
        top = cache.top_hits()
        self.assertNotIn("secret-prompt-key", str(top))
        self.assertEqual(len(top[0]["key_hash"]), 12)

    def test_expired_entries_drop_out(self):
        clock = FakeClock()
        cache = ResponseCache(max_entries=10, ttl_seconds=100, clock=clock)
        cache.put("k1", "answer")
        cache.get("k1")
        clock.t += 200   # past ttl — get() expires it
        self.assertIsNone(cache.get("k1"))
        self.assertEqual(cache.top_hits(), [])

    def test_limit_respected(self):
        cache = ResponseCache(max_entries=10, ttl_seconds=100,
                              clock=FakeClock())
        for i in range(7):
            cache.put(f"k{i}", f"answer {i}")
            cache.get(f"k{i}")
        self.assertEqual(len(cache.top_hits(limit=5)), 5)


class BrainTopHitsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_brain_includes_cache_top_hits(self):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        from kernel.config import Config
        from kernel.daemon import AgentDaemon
        daemon = AgentDaemon(Config(
            {"memory": {"db_path": str(
                __import__("pathlib").Path(__import__("tempfile")
                                          .mkdtemp()) / "t.db")}}))
        await daemon.memory.connect()
        daemon.brain.cache.put("hot-key", "cached answer")
        daemon.brain.cache.get("hot-key")
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            body = await (await client.get("/api/brain")).json()
            self.assertIn("cache_top_hits", body)
            self.assertEqual(body["cache_top_hits"][0]["hits"], 1)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()
