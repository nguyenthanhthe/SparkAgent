"""Brain demo: tier routing, circuit breaking, cache, cost — offline.

Two mock tiers show failover economics without any network:

    python examples/brain_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.adapters.base import AdapterResponse       # noqa: E402
from brain.adapters.mock import MockAdapter           # noqa: E402
from brain.cache import ResponseCache                 # noqa: E402
from brain.cost import CostTracker                    # noqa: E402
from brain.router import Tier, TierRouter             # noqa: E402


class LocalTier(MockAdapter):
    """Simulated GPU tier: fast, occasionally down."""

    def __init__(self):
        super().__init__()
        self.model = "nemotron-mini"
        self.name = "local"

    async def chat(self, messages, **kw):
        response = await super().chat(messages, **kw)
        return AdapterResponse(text=response.text, model=self.model,
                               prompt_tokens=response.prompt_tokens,
                               completion_tokens=response.completion_tokens)


class RemoteTier(LocalTier):
    def __init__(self):
        super().__init__()
        self.model = "glm-5.3"
        self.name = "remote"


async def main() -> None:
    local = LocalTier()
    remote = RemoteTier()
    costs = CostTracker()
    router = TierRouter(
        [Tier("local", local, priority=10),
         Tier("remote", remote, priority=20)],
        cache=ResponseCache(), costs=costs)

    print("1. healthy local tier answers:")
    result = await router.chat([{"role": "user", "content": "hi"}])
    print("   tier:", result.tier)

    print("2. local fails -> failover to remote:")
    local.fail_next = 1
    result = await router.chat([{"role": "user", "content": "hello again"}])
    print("   tier:", result.tier)

    print("3. identical request -> served from cache:")
    cached = await router.chat([{"role": "user", "content": "hi"}])
    print("   from_cache:", cached.from_cache)

    print("4. cost ledger:")
    router.costs.record("glm-5.3", 1500, 400, tier="remote")
    router.costs.record("nemotron-mini", 50000, 9000, tier="local")
    report = costs.report()
    for model, row in report["by_model"].items():
        print(f"   {model:<14} ${row['cost_usd']:.4f} "
              f"({row['calls']} calls)")


if __name__ == "__main__":
    asyncio.run(main())
