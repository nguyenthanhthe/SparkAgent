import unittest

from brain.bridge import Brain, BrainUnavailable, Tier
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault


class StreamClient:
    model = "fake-model"
    last_usage = {"prompt_tokens": 7, "completion_tokens": 3,
                  "total_tokens": 10}

    def __init__(self, chunks=("hel", "lo"), pre_error=None,
                 mid_error=None):
        self.chunks = list(chunks)
        self.pre_error = pre_error
        self.mid_error = mid_error

    async def chat_stream(self, messages, **kw):
        if self.pre_error:
            raise RuntimeError(self.pre_error)
        for i, chunk in enumerate(self.chunks):
            if self.mid_error and i == len(self.chunks) - 1:
                raise RuntimeError(self.mid_error)
            yield chunk


def make_brain(local, remote):
    brain = Brain(Config.load(), SecretVault(), EventBus())
    brain.local = local
    brain.remote = remote
    return brain


class BrainStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_stream_preferred(self):
        brain = make_brain(StreamClient(), StreamClient(chunks=["r"]))
        deltas = [d async for d in brain.chat_stream([{"role": "user",
                                                       "content": "q"}])]
        self.assertEqual(deltas, ["hel", "lo"])

    async def test_pre_chunk_failure_fails_over(self):
        brain = make_brain(StreamClient(pre_error="daemon down"),
                           StreamClient(chunks=["remote"]))
        deltas = [d async for d in brain.chat_stream([{"role": "user",
                                                       "content": "q"}])]
        self.assertEqual(deltas, ["remote"])
        self.assertEqual(brain._state[Tier.LOCAL].failures, 1)

    async def test_mid_stream_failure_propagates(self):
        brain = make_brain(StreamClient(mid_error="connection reset"),
                           StreamClient(chunks=["r"]))
        with self.assertRaises(RuntimeError):
            [d async for d in brain.chat_stream([{"role": "user",
                                                  "content": "q"}])]

    async def test_all_tiers_down_raises_unavailable(self):
        brain = make_brain(StreamClient(pre_error="x"),
                           StreamClient(pre_error="y"))
        with self.assertRaises(BrainUnavailable):
            [d async for d in brain.chat_stream([{"role": "user",
                                                  "content": "q"}])]

    async def test_completed_stream_records_usage(self):
        brain = make_brain(StreamClient(), StreamClient(chunks=["r"]))
        [d async for d in brain.chat_stream([{"role": "user",
                                              "content": "q"}])]
        row = brain.cost_report()["by_model"]["fake-model"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["prompt_tokens"], 7)
        self.assertEqual(row["completion_tokens"], 3)

    async def test_disabled_tier_skipped(self):
        brain = make_brain(StreamClient(pre_error="x"),
                           StreamClient(chunks=["r"]))
        brain.local_enabled = False
        deltas = [d async for d in brain.chat_stream([{"role": "user",
                                                       "content": "q"}])]
        self.assertEqual(deltas, ["r"])


if __name__ == "__main__":
    unittest.main()
