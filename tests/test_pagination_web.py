import unittest

from interface.cli import SparkCli


class CliEnvelopeTests(unittest.TestCase):
    """CLI task listing must unwrap the new pagination envelope."""

    def test_envelope_unwrapped(self):
        lines = []

        def transport(url, method, body):
            assert url.endswith("/api/tasks")
            return {"items": [{"id": 1, "status": "pending",
                               "goal": "envelope goal", "enabled": 1}],
                    "offset": 0, "limit": 50, "total": 1,
                    "has_more": False, "next_offset": None}

        cli = SparkCli(transport=transport, out=lines.append)
        cli.execute("tasks")
        text = "\n".join(lines)
        self.assertIn("envelope goal", text)

    def test_raw_array_still_supported(self):
        lines = []

        def transport(url, method, body):
            return [{"id": 2, "status": "done", "goal": "legacy shape",
                     "enabled": 1}]

        cli = SparkCli(transport=transport, out=lines.append)
        cli.execute("tasks")
        self.assertIn("legacy shape", "\n".join(lines))


class WebEnvelopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tasks_and_episodes_envelopes(self):
        import tempfile
        from pathlib import Path
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        from kernel.config import Config
        from kernel.daemon import AgentDaemon

        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            for _ in range(3):
                await daemon.memory.submit_task(f"goal {_}", "test")
            response = await client.get("/api/tasks?limit=2&offset=0")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(len(body["items"]), 2)
            self.assertTrue(body["has_more"])
            self.assertEqual(body["next_offset"], 2)

            response = await client.get("/api/tasks?offset=notanint")
            self.assertEqual(response.status, 400)

            eid = await daemon.memory.start_episode("ep #tagged-goal", "t")
            await daemon.memory.finish_episode(eid, "done", "a", "l", 1)
            response = await client.get("/api/episodes?limit=1")
            body = await response.json()
            self.assertEqual(body["total"], 1)
            self.assertEqual(body["items"][0]["goal"], "ep #tagged-goal")

            response = await client.get("/api/episodes?tag=tagged-goal")
            body = await response.json()
            self.assertEqual(body["total"], 1)
            response = await client.get("/api/episodes?tag=missing")
            body = await response.json()
            self.assertEqual(body["total"], 0)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()
