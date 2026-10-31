import unittest

from brain.adapters.base import AdapterResponse, ChatAdapter
from brain.adapters.mock import MockAdapter
from brain.adapters.ollama import OllamaAdapter
from brain.adapters.openai_compat import (OpenAICompatAdapter,
                                          RemoteNotConfigured)
from brain.adapters.registry import AdapterRegistry, UnknownAdapter
from brain.adapters import adapter_registry
from openshell.vault import SecretVault


class BaseProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_response_token_math(self):
        response = AdapterResponse(text="x", model="m", prompt_tokens=10,
                                   completion_tokens=5)
        self.assertEqual(response.total_tokens, 15)
        self.assertIsNone(AdapterResponse(text="x", model="m").total_tokens)

    async def test_close_is_optional_noop(self):
        class Minimal(ChatAdapter):
            async def chat(self, messages, **kw):
                return AdapterResponse("t", "m")

            async def healthy(self):
                return True, "ok"

        adapter = Minimal()
        await adapter.close()  # must not raise
        self.assertEqual(adapter.describe()["kind"], "Minimal")


class MockAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_replies_in_order(self):
        adapter = MockAdapter()
        adapter.enqueue("first", "second")
        first = await adapter.chat([{"role": "user", "content": "a"}])
        second = await adapter.chat([{"role": "user", "content": "b"}])
        self.assertEqual((first.text, second.text), ("first", "second"))

    async def test_scripted_exception_raises(self):
        adapter = MockAdapter()
        adapter.enqueue(ValueError("boom"))
        with self.assertRaises(ValueError):
            await adapter.chat([{"role": "user", "content": "x"}])

    async def test_deterministic_when_unscripted(self):
        adapter = MockAdapter()
        messages = [{"role": "user", "content": "hello"}]
        one = await adapter.chat(messages)
        two = await adapter.chat(messages)
        self.assertEqual(one.text, two.text)

    async def test_json_mode_returns_json(self):
        import json
        adapter = MockAdapter()
        response = await adapter.chat([{"role": "user", "content": "q"}],
                                      json_mode=True)
        parsed = json.loads(response.text)
        self.assertIn("seed", parsed)

    async def test_fail_next_counter(self):
        adapter = MockAdapter(fail_next=2)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await adapter.chat([{"role": "user", "content": "x"}])
        response = await adapter.chat([{"role": "user", "content": "x"}])
        self.assertTrue(response.text)

    async def test_healthy_always_true(self):
        self.assertEqual(await MockAdapter().healthy(), (True, "mock always healthy"))


class FakePoster:
    """Offline poster for the OpenAI-compatible adapter."""

    def __init__(self, responses=None, status=200):
        self.responses = list(responses or [])
        self.status = status
        self.requests = []

    async def __call__(self, url, headers, payload):
        self.requests.append({"url": url, "headers": headers,
                              "payload": payload})
        if self.status != 200:
            body = {"error": "induced"}
            from brain.adapters.openai_compat import _http_error
            raise _http_error(self.status, body)
        body = self.responses.pop(0) if self.responses else {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 2},
            "model": "fake"}
        return body


class OpenAICompatTests(unittest.IsolatedAsyncioTestCase):
    def make(self, poster, vault=None, **kw):
        adapter = OpenAICompatAdapter(_poster=poster, _vault=vault, **kw)
        return adapter

    async def test_chat_parses_response(self):
        poster = FakePoster()
        adapter = self.make(poster)
        import os
        old = os.environ.get("GLM_API_KEY")
        os.environ["GLM_API_KEY"] = "unit-test-key"
        try:
            response = await adapter.chat([{"role": "user", "content": "hi"}])
            self.assertEqual(response.text, "ok")
            self.assertEqual(response.prompt_tokens, 9)
            self.assertEqual(response.total_tokens, 11)
            auth = poster.requests[0]["headers"]["Authorization"]
            self.assertEqual(auth, "Bearer unit-test-key")
        finally:
            if old is None:
                os.environ.pop("GLM_API_KEY", None)
            else:
                os.environ["GLM_API_KEY"] = old

    async def test_missing_key_raises_before_http(self):
        adapter = self.make(FakePoster(), vault=SecretVault())
        adapter.api_key_name = "NO_SUCH_KEY_UNITTEST"
        with self.assertRaises(RemoteNotConfigured):
            await adapter.chat([{"role": "user", "content": "x"}])
        # no HTTP attempt made

    async def test_json_mode_sets_response_format(self):
        poster = FakePoster()
        adapter = self.make(poster)
        import os
        os.environ["GLM_API_KEY"] = "unit-test-key"
        try:
            await adapter.chat([{"role": "user", "content": "x"}],
                               json_mode=True)
            self.assertEqual(
                poster.requests[0]["payload"]["response_format"],
                {"type": "json_object"})
        finally:
            os.environ.pop("GLM_API_KEY", None)

    async def test_malformed_response_raises(self):
        poster = FakePoster(responses=[{"choices": []}])
        adapter = self.make(poster)
        import os
        os.environ["GLM_API_KEY"] = "unit-test-key"
        try:
            with self.assertRaises(RuntimeError):
                await adapter.chat([{"role": "user", "content": "x"}])
        finally:
            os.environ.pop("GLM_API_KEY", None)

    async def test_unauthorized_not_retried(self):
        from brain.adapters.openai_compat import _http_error
        calls = []

        async def poster(url, headers, payload):
            calls.append(1)
            raise _http_error(401, {"error": "bad key"})

        adapter = self.make(poster, max_retries=3)
        import os
        os.environ["GLM_API_KEY"] = "unit-test-key"
        try:
            with self.assertRaises(PermissionError):
                await adapter.chat([{"role": "user", "content": "x"}])
            self.assertEqual(len(calls), 1)  # 401 aborts immediately
        finally:
            os.environ.pop("GLM_API_KEY", None)

    async def test_healthy_without_key(self):
        adapter = self.make(None, vault=SecretVault())
        adapter.api_key_name = "NO_SUCH_KEY_UNITTEST"
        ok, detail = await adapter.healthy()
        self.assertFalse(ok)
        self.assertIn("not set", detail)


class OllamaAdapterTests(unittest.TestCase):
    def test_from_config_defaults(self):
        adapter = OllamaAdapter.from_config({})
        self.assertEqual(adapter.model, "nemotron-mini")
        self.assertIn("11434", adapter.base_url)

    def test_from_config_overrides(self):
        adapter = OllamaAdapter.from_config(
            {"model": "llama3", "base_url": "http://host:1", "num_ctx": 4096})
        self.assertEqual(adapter.model, "llama3")
        self.assertEqual(adapter.num_ctx, 4096)


class AdapterRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_adapters_registered(self):
        self.assertIn("mock", adapter_registry.available())
        self.assertIn("ollama", adapter_registry.available())
        self.assertIn("openai_compat", adapter_registry.available())

    async def test_create_mock(self):
        adapter = adapter_registry.create("mock", {"model": "zz"}, SecretVault())
        self.assertEqual(adapter.model, "zz")

    async def test_unknown_adapter_raises(self):
        with self.assertRaises(UnknownAdapter):
            adapter_registry.create("nope", {}, SecretVault())

    async def test_duplicate_registration_blocked_unless_replaced(self):
        registry = AdapterRegistry()
        registry.register("x", lambda cfg, vault: MockAdapter())
        with self.assertRaises(ValueError):
            registry.register("x", lambda cfg, vault: MockAdapter())
        registry.register("x", lambda cfg, vault: MockAdapter(), replace=True)
        self.assertEqual(registry.available(), ["x"])

    async def test_invalid_name_rejected(self):
        registry = AdapterRegistry()
        with self.assertRaises(ValueError):
            registry.register("bad name!", lambda cfg, vault: MockAdapter())

    async def test_unregister(self):
        registry = AdapterRegistry()
        registry.register("x", lambda cfg, vault: MockAdapter())
        self.assertTrue(registry.unregister("x"))
        self.assertFalse(registry.unregister("x"))

    async def test_ping_returns_latency_sample(self):
        probe = await MockAdapter().ping()
        self.assertTrue(probe["ok"])
        self.assertGreaterEqual(probe["latency_ms"], 0.0)

    async def test_ping_never_raises(self):
        class Boom(ChatAdapter):
            async def chat(self, messages, **kw):
                raise RuntimeError

            async def healthy(self):
                raise RuntimeError("probe exploded")

        probe = await Boom().ping()
        self.assertFalse(probe["ok"])
        self.assertIn("probe exploded", probe["detail"])
        self.assertGreaterEqual(probe["latency_ms"], 0.0)

    async def test_registry_ping_creates_and_probes(self):
        registry = AdapterRegistry()
        registry.register("x", lambda cfg, vault: MockAdapter())
        probe = await registry.ping("x", {}, SecretVault())
        self.assertTrue(probe["ok"])

    async def test_registry_ping_unknown_name(self):
        with self.assertRaises(UnknownAdapter):
            await adapter_registry.ping("nope", {}, SecretVault())

    async def test_registry_ping_keeps_last_five_samples(self):
        registry = AdapterRegistry()
        registry.register("x", lambda cfg, vault: MockAdapter())
        for _ in range(7):
            await registry.ping("x", {}, SecretVault())
        history = registry.latency_history["x"]
        self.assertEqual(len(history), 5)
        probe = await registry.ping("x", {}, SecretVault())
        self.assertEqual(len(probe["recent_ms"]), 5)

    async def test_registry_ping_records_failures(self):
        class _SickAdapter:
            model = "sick"

            async def ping(self):
                return {"ok": False, "detail": "connection refused",
                        "latency_ms": None}

            async def close(self):
                pass

        registry = AdapterRegistry()
        registry.register("sick", lambda cfg, vault: _SickAdapter())
        for _ in range(7):
            probe = await registry.ping("sick", {}, SecretVault())
            self.assertFalse(probe["ok"])
        failures = registry.failure_history["sick"]
        self.assertEqual(len(failures), 5)
        # structured entries: stamped and bounded
        self.assertEqual(failures[-1]["detail"], "connection refused")
        self.assertRegex(failures[-1]["at"], r"^\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()
