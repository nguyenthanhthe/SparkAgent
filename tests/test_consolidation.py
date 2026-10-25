import tempfile
import unittest
from pathlib import Path

from kernel.config import Config
from kernel.daemon import AgentDaemon
from kernel.memory import Memory


def run(coro):
    import asyncio
    return asyncio.run(coro)


class EpisodesWithoutDigestTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=64)

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def test_only_undigested_done_episodes(self):
        async def scenario():
            await self.mem.connect()
            done = await self.mem.start_episode("done goal", "t")
            await self.mem.finish_episode(done, "done", "answer", "l", 1)
            failed = await self.mem.start_episode("failed goal", "t")
            await self.mem.finish_episode(failed, "failed", "x", "l", 1)
            # mark the done episode as digested
            await self.mem.remember("[digested]", kind="digest-marker",
                                    key=f"episode:{done}")
            from datetime import datetime, timedelta
            old = (datetime.now() - timedelta(days=1)
                   ).isoformat(timespec="seconds")
            return await self.mem.episodes_without_digest(old, limit=10)
        pending = run(scenario())
        # failed episodes never qualify; the done one is already digested
        self.assertEqual(pending, [])

    def test_done_undigested_returned(self):
        async def scenario():
            await self.mem.connect()
            done = await self.mem.start_episode("fresh done", "t")
            await self.mem.finish_episode(done, "done", "outcome", "l", 1)
            from datetime import datetime, timedelta
            old = (datetime.now() - timedelta(days=1)
                   ).isoformat(timespec="seconds")
            return await self.mem.episodes_without_digest(old, limit=10)
        pending = run(scenario())
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["goal"], "fresh done")


class DaemonConsolidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_consolidate_creates_digest_memory(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        try:
            eid = await daemon.memory.start_episode(
                "measure gpu thermal output under load", "test")
            await daemon.memory.finish_episode(
                eid, "done",
                "GPU thermal output reached 95C during sustained inference "
                "and throttling reduced clocks by 15 percent", "local", 1)
            digested = await daemon._consolidate_episodes()
            self.assertEqual(digested, 1)
            # a second pass has nothing new to consolidate
            self.assertEqual(await daemon._consolidate_episodes(), 0)
            hits = await daemon.memory.recall("gpu thermal consolidation",
                                              k=5)
            kinds = {h.kind for h in hits}
            self.assertIn("digest", kinds)
        finally:
            await daemon.memory.close()

    async def test_digest_carries_episode_tags(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        try:
            eid = await daemon.memory.start_episode(
                "check gpu thermals #gpu #ops", "test")
            await daemon.memory.finish_episode(
                eid, "done", "thermals nominal", "local", 1)
            eid2 = await daemon.memory.start_episode(
                "rotate logs #ops", "test")
            await daemon.memory.finish_episode(
                eid2, "done", "logs rotated", "local", 1)
            digested = await daemon._consolidate_episodes()
            self.assertEqual(digested, 2)
            rows = await daemon.memory.recall("consolidation", k=10)
            digests = [h for h in rows if h.kind == "digest"]
            self.assertTrue(digests)
            digest = digests[0]
            self.assertIn("#gpu", digest.text)
            self.assertIn("#ops", digest.text)
        finally:
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()
