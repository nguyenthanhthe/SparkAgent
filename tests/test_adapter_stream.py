import unittest

from brain.adapters.mock import MockAdapter
from brain.adapters.openai_compat import (OpenAICompatAdapter,
                                          RemoteNotConfigured)


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_base_fallback_single_chunk(self):
        adapter = MockAdapter()
        adapter.enqueue("whole answer")
        chunks = [c async for c in adapter.chat_stream([{"role": "user",
                                                         "content": "q"}])]
        self.assertEqual(chunks, ["whole answer"])

    async def test_streamer_deltas(self):
        async def fake_stream(url, headers, payload):
            for delta in ["Hel", "lo ", "world"]:
                yield delta

        adapter = OpenAICompatAdapter(model="glm-5.3", _streamer=fake_stream,
                                      _vault=None)
        adapter._api_key = lambda: "k"          # type: ignore[assignment]
        chunks = [c async for c in adapter.chat_stream([{"role": "user",
                                                         "content": "q"}])]
        self.assertEqual(chunks, ["Hel", "lo ", "world"])

    async def test_missing_key_raises_before_first_delta(self):
        async def fake_stream(url, headers, payload):
            yield "never reached"
            raise AssertionError("streamer must not be called")

        adapter = OpenAICompatAdapter(model="glm-5.3", _streamer=fake_stream)
        adapter._api_key = lambda: None         # type: ignore[assignment]
        with self.assertRaises(RemoteNotConfigured):
            [c async for c in adapter.chat_stream([{"role": "user",
                                                    "content": "q"}])]

    async def test_empty_stream_raises(self):
        async def fake_stream(url, headers, payload):
            return
            yield  # pragma: no cover — makes it an async generator

        adapter = OpenAICompatAdapter(model="glm-5.3", _streamer=fake_stream)
        adapter._api_key = lambda: "k"          # type: ignore[assignment]
        with self.assertRaises(RuntimeError):
            [c async for c in adapter.chat_stream([{"role": "user",
                                                    "content": "q"}])]

    async def test_streamer_error_propagates(self):
        async def fake_stream(url, headers, payload):
            yield "partial"
            raise ConnectionResetError("server error (502)")

        adapter = OpenAICompatAdapter(model="glm-5.3", _streamer=fake_stream)
        adapter._api_key = lambda: "k"          # type: ignore[assignment]
        with self.assertRaises(ConnectionResetError):
            [c async for c in adapter.chat_stream([{"role": "user",
                                                    "content": "q"}])]

    async def test_no_streamer_falls_back_to_chat(self):
        class FakePoster:
            async def __call__(self, url, headers, payload):
                assert payload["stream"] is False, \
                    "fallback must request non-streaming completions"
                return {"model": "glm-5.3",
                        "choices": [{"message": {"content": "fallback text"}}],
                        "usage": {"prompt_tokens": 1,
                                  "completion_tokens": 2}}

        adapter = OpenAICompatAdapter(model="glm-5.3", _poster=FakePoster())
        adapter._api_key = lambda: "k"          # type: ignore[assignment]
        chunks = [c async for c in adapter.chat_stream([{"role": "user",
                                                         "content": "q"}])]
        self.assertEqual(chunks, ["fallback text"])

    async def test_close_closes_streamer_session(self):
        closed = []

        async def fake_stream(url, headers, payload):
            yield "x"

        async def close_session():
            closed.append(True)

        fake_stream.close_session = close_session
        adapter = OpenAICompatAdapter(model="glm-5.3", _streamer=fake_stream)
        await adapter.close()
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
