"""Adapter registry — name → factory, with builtin provider registration.

Factories receive ``(config_section, vault)`` so providers can pull their
own credentials (never stored in config). The registry is global so third
parties can register adapters at import time; ``create`` instantiates by
name.
"""

from __future__ import annotations

from typing import Any, Callable

from brain.adapters.base import ChatAdapter
from openshell.vault import SecretVault

Factory = Callable[[dict[str, Any], SecretVault], ChatAdapter]


class UnknownAdapter(ValueError):
    pass


class AdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Factory] = {}
        # name -> last-5 latency samples (ms), recorded by ping()
        self.latency_history: dict[str, list[float]] = {}
        # name -> last-5 probe failure details, recorded by ping()
        self.failure_history: dict[str, list[str]] = {}

    def register(self, name: str, factory: Factory,
                 *, replace: bool = False) -> None:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"invalid adapter name {name!r}")
        if name in self._factories and not replace:
            raise ValueError(f"adapter {name!r} already registered")
        self._factories[name] = factory

    def create(self, name: str, config: dict[str, Any],
               vault: SecretVault) -> ChatAdapter:
        factory = self._factories.get(name)
        if factory is None:
            raise UnknownAdapter(
                f"no adapter named {name!r}; registered: {self.available()}")
        return factory(config, vault)

    def available(self) -> list[str]:
        return sorted(self._factories)

    def unregister(self, name: str) -> bool:
        return self._factories.pop(name, None) is not None

    async def ping(self, name: str, config: dict[str, Any],
                   vault: SecretVault) -> dict[str, Any]:
        """Create the named adapter, take one latency sample, release it.

        Raises :class:`UnknownAdapter` for unregistered names; any other
        failure surfaces inside the returned probe (ok=False). The last
        five samples per name are kept in ``latency_history``."""
        adapter = self.create(name, config, vault)
        try:
            probe = await adapter.ping()
        finally:
            await adapter.close()
        if probe.get("ok") is False:
            failures = self.failure_history.setdefault(name, [])
            failures.append(str(probe.get("detail") or "probe failed")[:120])
            self.failure_history[name] = failures[-5:]
        if probe.get("latency_ms") is not None:
            history = self.latency_history.setdefault(name, [])
            history.append(float(probe["latency_ms"]))
            self.latency_history[name] = history[-5:]
            probe["recent_ms"] = list(self.latency_history[name])
        return probe


def _register_builtins(registry: AdapterRegistry) -> None:
    from brain.adapters.mock import MockAdapter
    from brain.adapters.ollama import OllamaAdapter
    from brain.adapters.openai_compat import OpenAICompatAdapter

    registry.register("mock", lambda cfg, vault: MockAdapter.from_config(cfg))
    registry.register(
        "ollama", lambda cfg, vault: OllamaAdapter.from_config(cfg))
    registry.register(
        "openai_compat",
        lambda cfg, vault: OpenAICompatAdapter.from_config(cfg, vault))


adapter_registry = AdapterRegistry()
_register_builtins(adapter_registry)
