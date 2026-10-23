import unittest

from brain.bridge import Brain, BrainUnavailable, Tier
from brain.cost import CostTracker
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault
from tests.test_brain import FakeLocal, FakeRemote


def make_brain(local, remote, budget_guard=None):
    brain = Brain(Config.load(), SecretVault(), EventBus())
    brain.local = local
    brain.remote = remote
    brain.budget_guard = budget_guard
    return brain


class BudgetGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_skipped_when_budget_exhausted(self):
        async def over_budget():
            return False

        local = FakeLocal(error="ollama down")
        remote = FakeRemote(text="would cost money")
        brain = make_brain(local, remote, budget_guard=over_budget)
        with self.assertRaises(BrainUnavailable) as ctx:
            await brain.chat([{"role": "user", "content": "hi"}])
        errors = ctx.exception.errors
        self.assertIn("budget", errors["remote"])

    async def test_remote_used_within_budget(self):
        async def within_budget():
            return True

        local = FakeLocal(error="ollama down")
        remote = FakeRemote(text="cheap answer")
        brain = make_brain(local, remote, budget_guard=within_budget)
        result = await brain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.tier, Tier.REMOTE)

    async def test_local_unaffected_by_budget(self):
        async def over_budget():
            return False

        local = FakeLocal(text="free local answer")
        brain = make_brain(local, FakeRemote(text="r"),
                           budget_guard=over_budget)
        result = await brain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.tier, Tier.LOCAL)

    async def test_guard_exception_does_not_block(self):
        async def broken_guard():
            raise RuntimeError("ledger offline")

        local = FakeLocal(error="down")
        remote = FakeRemote(text="fallback fine")
        brain = make_brain(local, remote, budget_guard=broken_guard)
        result = await brain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.tier, Tier.REMOTE)

    async def test_cost_tracker_e2e_veto(self):
        costs = CostTracker()
        costs.record("glm-5.3", 2_000_000, 0, tier="remote")  # 1.20 USD

        async def guard():
            return costs.within_budget(1.0)

        brain = make_brain(FakeLocal(error="down"), FakeRemote(text="x"),
                           budget_guard=guard)
        with self.assertRaises(BrainUnavailable):
            await brain.chat([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
