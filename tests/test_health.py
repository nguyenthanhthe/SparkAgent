import asyncio
import unittest

from kernel.health import HealthRegistry, HealthStatus, Status


class HealthRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_ok(self):
        registry = HealthRegistry()
        registry.register("db", lambda: _status(Status.OK, "connected"))
        registry.register("brain", lambda: _status(Status.OK, "local tier"))
        report = await registry.check_all()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["checks"]), 2)

    async def test_degraded_wins_over_ok(self):
        registry = HealthRegistry()
        registry.register("db", lambda: _status(Status.OK))
        registry.register("brain", lambda: _status(Status.DEGRADED,
                                                   "cooldown"))
        report = await registry.check_all()
        self.assertEqual(report["status"], "degraded")

    async def test_down_wins_over_everything(self):
        registry = HealthRegistry()
        registry.register("a", lambda: _status(Status.OK))
        registry.register("b", lambda: _status(Status.DEGRADED))
        registry.register("c", lambda: _status(Status.DOWN, "dead"))
        report = await registry.check_all()
        self.assertEqual(report["status"], "down")

    async def test_exception_becomes_down(self):
        registry = HealthRegistry()

        async def broken():
            raise RuntimeError("boom")

        registry.register("broken", broken)
        report = await registry.check_all()
        self.assertEqual(report["status"], "down")
        self.assertIn("boom", report["checks"][0]["detail"])

    async def test_timeout_becomes_down(self):
        registry = HealthRegistry(timeout=0.05)

        async def slow():
            await asyncio.sleep(1)
            return HealthStatus(Status.OK)

        registry.register("slow", slow)
        report = await registry.check_all()
        self.assertEqual(report["status"], "down")
        self.assertIn("timed out", report["checks"][0]["detail"])

    async def test_unregister(self):
        registry = HealthRegistry()
        registry.register("x", lambda: _status(Status.OK))
        registry.unregister("x")
        report = await registry.check_all()
        self.assertEqual(report["checks"], [])
        self.assertEqual(report["status"], "ok")


async def _status(status: Status, detail: str = ""):
    return HealthStatus(status, detail)


if __name__ == "__main__":
    unittest.main()
