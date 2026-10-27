import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon
from security.auth_limiter import AuthRateLimiter


class WebAuthRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, max_failures: int = 3):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        real_get = daemon.vault.get
        daemon.vault.get = lambda name: "sekrit" \
            if name == "SPARKAGENT_WEB_TOKEN" else real_get(name)
        app = build_web_app(daemon)
        app["auth_limiter"] = AuthRateLimiter(max_failures=max_failures,
                                              window_seconds=300,
                                              lockout_seconds=300)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return daemon, client

    async def test_wrong_token_four_oh_one(self):
        daemon, client = await self._setup()
        try:
            response = await client.get("/api/status",
                                        headers={"Authorization":
                                                 "Bearer wrong"})
            self.assertEqual(response.status, 401)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_lockout_after_repeated_failures(self):
        daemon, client = await self._setup(max_failures=3)
        try:
            for _ in range(3):
                response = await client.get("/api/status",
                                            headers={"Authorization":
                                                     "Bearer nope"})
                self.assertEqual(response.status, 401)
            # lockout: even a correct token now gets 429
            response = await client.get(
                "/api/status",
                headers={"Authorization": "Bearer sekrit"})
            self.assertEqual(response.status, 429)
            self.assertIn("Retry-After", response.headers)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_correct_token_not_limited(self):
        daemon, client = await self._setup()
        try:
            response = await client.get(
                "/api/status", headers={"Authorization": "Bearer sekrit"})
            self.assertEqual(response.status, 200)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_db_lookups_require_token(self):
        daemon, client = await self._setup()
        try:
            response = await client.get("/api/db/tasks")
            self.assertEqual(response.status, 401)
            response = await client.get(
                "/api/db/tasks",
                headers={"Authorization": "Bearer wrong"})
            self.assertEqual(response.status, 401)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_db_failures_lock_out_db_too(self):
        daemon, client = await self._setup(max_failures=3)
        try:
            for _ in range(3):
                response = await client.get(
                    "/api/db/tasks",
                    headers={"Authorization": "Bearer nope"})
                self.assertEqual(response.status, 401)
            # lockout is client-wide: a valid token on /api/db gets 429
            response = await client.get(
                "/api/db/tasks",
                headers={"Authorization": "Bearer sekrit"})
            self.assertEqual(response.status, 429)
            self.assertIn("Retry-After", response.headers)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_db_lookup_with_valid_token(self):
        daemon, client = await self._setup()
        try:
            response = await client.get(
                "/api/db/tasks",
                headers={"Authorization": "Bearer sekrit"})
            self.assertEqual(response.status, 200)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_status_exposes_lockout_state(self):
        daemon, client = await self._setup(max_failures=3)
        try:
            for _ in range(2):
                await client.get("/api/status",
                                 headers={"Authorization": "Bearer bad"})
            response = await client.get(
                "/api/status",
                headers={"Authorization": "Bearer sekrit"})
            auth = (await response.json())["auth"]
            self.assertEqual(auth["locked_now"], 0)
            self.assertEqual(auth["failures_recorded"], 2)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()
