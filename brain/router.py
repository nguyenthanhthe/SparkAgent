"""Tier router — ordered failover across chat adapters.

Combines the primitives built in this wave: per-tier circuit breakers,
health caching with TTL, optional response cache, cost recording, and a
per-tier veto hook (the daemon wires the VRAM guard here). Tiers are tried
in declared order; the first healthy tier that completes the request wins.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from brain.adapters.base import AdapterResponse, ChatAdapter
from brain.cache import ResponseCache, cache_key
from brain.cost import CostTracker
from kernel.circuit import CircuitBreaker
from kernel.clock import Clock
from kernel.logging import get_logger

logger = get_logger("router")

Guard = Callable[[], Awaitable[bool]]


@dataclass
class Tier:
    name: str
    adapter: ChatAdapter
    priority: int = 100          # lower = tried first
    veto: Guard | None = None


@dataclass
class RouteResult:
    response: AdapterResponse
    tier: str
    from_cache: bool = False


class TierRouter:
    def __init__(self, tiers: list[Tier], *,
                 cache: ResponseCache | None = None,
                 costs: CostTracker | None = None,
                 health_ttl: float = 30.0,
                 clock: Clock | None = None,
                 failure_threshold: int = 3, reset_timeout: float = 60.0):
        if not tiers:
            raise ValueError("router needs at least one tier")
        self.tiers = sorted(tiers, key=lambda t: t.priority)
        self.cache = cache
        self.costs = costs
        self.health_ttl = health_ttl
        self.clock = clock or Clock()
        self._breakers = {tier.name: CircuitBreaker(
            name=tier.name, failure_threshold=failure_threshold,
            reset_timeout=reset_timeout, clock=self.clock)
            for tier in self.tiers}
        self._health_cache: dict[str, tuple[float, bool, str]] = {}
        self._veto_cache: dict[str, tuple[float, bool]] = {}
        self.stats = {tier.name: {"requests": 0, "failures": 0,
                                  "cache_hits": 0} for tier in self.tiers}

    # ------------------------------------------------------------------ chat
    async def chat(self, messages: list[dict], *,
                   force: str | None = None,
                   temperature: float | None = None,
                   json_mode: bool = False,
                   use_cache: bool = True) -> RouteResult:
        candidates = self.tiers
        if force is not None:
            candidates = [t for t in self.tiers if t.name == force]
            if not candidates:
                raise ValueError(f"unknown tier {force!r}")

        cache_id = None
        if use_cache and self.cache is not None:
            first_model = candidates[0].adapter.model
            cache_id = cache_key(first_model, messages,
                                 temperature=temperature,
                                 json_mode=json_mode)
            entry = self.cache.get(cache_id)
            if entry is not None:
                self.stats[candidates[0].name]["cache_hits"] += 1
                response = AdapterResponse(
                    text=entry.text, model=first_model,
                    elapsed_s=0.0,
                    extra={"cached": True})
                if self.costs is not None:
                    self.costs.record(first_model, 0, 0,
                                      tier=candidates[0].name, cached=True)
                return RouteResult(response, candidates[0].name,
                                   from_cache=True)

        errors: dict[str, str] = {}
        for tier in candidates:
            if not await self._allowed(tier):
                errors[tier.name] = "tier unavailable (health/veto/circuit)"
                continue
            try:
                self.stats[tier.name]["requests"] += 1
                response = await self._breakers[tier.name].call(
                    tier.adapter.chat, messages,
                    temperature=temperature, json_mode=json_mode)
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001 — failover, not crash
                self.stats[tier.name]["failures"] += 1
                errors[tier.name] = f"{type(exc).__name__}: {exc}"
                logger.warning("tier %s failed: %s", tier.name,
                               errors[tier.name])
                continue
            if self.costs is not None:
                self.costs.record(response.model,
                                  response.prompt_tokens or 0,
                                  response.completion_tokens or 0,
                                  tier=tier.name)
            if cache_id is not None and self.cache is not None:
                self.cache.put(cache_id, response.text, {
                    "total_tokens": response.total_tokens or 0})
            return RouteResult(response, tier.name)

        raise RuntimeError("all tiers failed: "
                           + "; ".join(f"{n}: {e}" for n, e in errors.items()))

    # -------------------------------------------------------------- admission
    async def _allowed(self, tier: Tier) -> bool:
        breaker = self._breakers[tier.name]
        if breaker.state.value == "open":
            return False
        now = self.clock.now()
        cached = self._health_cache.get(tier.name)
        if cached is None or now - cached[0] > self.health_ttl:
            ok, detail = await tier.adapter.healthy()
            self._health_cache[tier.name] = (now, ok, detail)
            cached = (now, ok, detail)
        if not cached[1]:
            return False
        if tier.veto is not None:
            veto = self._veto_cache.get(tier.name)
            if veto is None or now - veto[0] > 5.0:
                try:
                    allowed = await tier.veto()
                except Exception:  # noqa: BLE001 — veto must never kill chat
                    allowed = True
                self._veto_cache[tier.name] = (now, allowed)
                veto = (now, allowed)
            if not veto[1]:
                return False
        return True

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {"tiers": [
            {"name": tier.name, "model": tier.adapter.model,
             "priority": tier.priority,
             "circuit": self._breakers[tier.name].snapshot(),
             "stats": self.stats[tier.name]}
            for tier in self.tiers]}

    async def close(self) -> None:
        for tier in self.tiers:
            await tier.adapter.close()

    def invalidate_health(self, name: str | None = None) -> None:
        if name is None:
            self._health_cache.clear()
        else:
            self._health_cache.pop(name, None)
