"""Failure-ledger demo: adapter probe failures with timestamps, offline.

A flaky adapter fails more than it succeeds; the registry keeps the
last five probe failures, each stamped — the same ledger /api/adapters
serves and the dashboard adapters card renders.

    python examples/failure_ledger_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.adapters.registry import AdapterRegistry   # noqa: E402
from openshell.vault import SecretVault   # noqa: E402


class FlakyAdapter:
    """Fails twice, succeeds once, in a loop."""

    model = "flaky-local"
    counter = 0

    async def ping(self):
        FlakyAdapter.counter += 1
        if FlakyAdapter.counter % 3 != 0:
            return {"ok": False, "detail": "connection refused "
                                           "(attempt %d)" % FlakyAdapter.counter,
                    "latency_ms": None}
        return {"ok": True, "detail": "ok", "latency_ms": 42.5}

    async def close(self):
        pass


async def main() -> None:
    registry = AdapterRegistry()
    registry.register("flaky", lambda cfg, vault: FlakyAdapter())
    for _ in range(9):
        await registry.ping("flaky", {}, SecretVault())

    print("latency history (successful probes only):")
    print(f"  {registry.latency_history.get('flaky')}")
    print("failure ledger (newest last, stamped):")
    for entry in registry.failure_history.get("flaky", []):
        print(f"  {entry}")


if __name__ == "__main__":
    asyncio.run(main())
