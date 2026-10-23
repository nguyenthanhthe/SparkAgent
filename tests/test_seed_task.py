import tempfile
import unittest
from pathlib import Path

from kernel.config import Config
from kernel.daemon import AgentDaemon


class SeedDailyTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_seeds_on_empty_store(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        try:
            await daemon._seed_daily_digest_task()
            rows = await daemon.memory.list_tasks(limit=5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["daily_at"], "08:00")
            self.assertEqual(rows[0]["source"], "daemon")
            self.assertIn("digest", rows[0]["goal"])
        finally:
            await daemon.memory.close()

    async def test_no_seed_when_tasks_exist(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        try:
            await daemon.memory.submit_task("existing", "operator")
            await daemon._seed_daily_digest_task()
            rows = await daemon.memory.list_tasks(limit=5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["goal"], "existing")
        finally:
            await daemon.memory.close()

    async def test_config_opt_out(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)},
                                     "agent": {"seed_daily_task": False}}))
        await daemon.memory.connect()
        try:
            await daemon._seed_daily_digest_task()
            self.assertEqual(await daemon.memory.list_tasks(limit=5), [])
        finally:
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()
