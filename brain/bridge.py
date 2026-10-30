"""Dual-tier brain: local Nemotron first, remote GLM fallback.

Routing rules:
  - If ``force`` is set, only that tier is tried.
  - Otherwise tiers are tried in order [local, remote] (skipping disabled ones).
  - A tier that fails ``fallback_after_failures`` times in a row enters a
    60-second cooldown and is skipped (unless forced) so the agent does not
    stall on a dead Ollama daemon.
  - An optional ``resource_guard`` async callable (wired by the daemon to a
    VRAM check) can veto the local tier before each request.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from brain.cache import ResponseCache, cache_key as cache_key_of
from brain.cost import CostTracker
from brain.local import OllamaClient
from brain.remote import OpenAICompatClient
from kernel.bus import EventBus
from kernel.logging import get_logger
from kernel.config import Config
from openshell.vault import SecretVault

logger = get_logger("brain")


class Tier(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class BrainUnavailable(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        detail = "; ".join(f"{tier}: {err}" for tier, err in errors.items())
        super().__init__(f"all LLM tiers failed — {detail}")


@dataclass
class BrainResponse:
    text: str
    tier: Tier
    model: str
    elapsed: float


@dataclass
class _TierState:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    requests: int = 0
    served: int = 0
    failures: int = 0
    last_error: str | None = None


@dataclass
class Brain:
    cfg: Config
    vault: SecretVault
    bus: EventBus
    resource_guard: Callable[[], Awaitable[bool]] | None = field(default=None)
    budget_guard: Callable[[], Awaitable[bool]] | None = field(default=None)

    def __post_init__(self) -> None:
        local_cfg = self.cfg.section("brain.local")
        remote_cfg = self.cfg.section("brain.remote")
        self.local_enabled = bool(local_cfg.get("enabled", True))
        self.remote_enabled = bool(remote_cfg.get("enabled", True))
        self.local = OllamaClient(
            base_url=local_cfg.get("base_url") or "http://127.0.0.1:11434",
            model=local_cfg.get("model") or "nemotron-mini",
            timeout=float(local_cfg.get("timeout") or 180),
            num_ctx=int(local_cfg.get("num_ctx") or 8192),
            temperature=float(local_cfg.get("temperature", 0.4)))
        self.remote = OpenAICompatClient(
            chat_url=remote_cfg.get("chat_url")
            or "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            api_key_provider=lambda: self.vault.get("GLM_API_KEY"),
            model=remote_cfg.get("model") or "glm-5.3",
            timeout=float(remote_cfg.get("timeout") or 120),
            temperature=float(remote_cfg.get("temperature", 0.4)))
        self._fallback_after = int(self.cfg.get("brain.fallback_after_failures", 2))
        self._cooldown_seconds = 60.0
        self.cache_enabled = bool(self.cfg.get("brain.cache_responses",
                                                False))
        self.cache = ResponseCache(
            max_entries=int(self.cfg.get("brain.cache_entries", 256)),
            ttl_seconds=float(self.cfg.get("brain.cache_ttl", 900)))
        self.cache_hits = 0
        self.costs = CostTracker()
        self._state: dict[Tier, _TierState] = {Tier.LOCAL: _TierState(),
                                               Tier.REMOTE: _TierState()}

    # ------------------------------------------------------------------- chat
    async def chat(self, messages: list[dict[str, str]],
                   force: Tier | None = None,
                   json_mode: bool = False,
                   temperature: float | None = None) -> BrainResponse:
        order = [force] if force else [Tier.LOCAL, Tier.REMOTE]

        cache_key = None
        if self.cache_enabled and force is None:
            first_model = self.local.model if self.local_enabled else \
                self.remote.model
            cache_params: dict = {"json_mode": json_mode}
            if temperature is not None:
                cache_params["temperature"] = temperature
            cache_key = cache_key_of(first_model, messages, **cache_params)
            entry = self.cache.get(cache_key)
            if entry is not None:
                self.cache_hits += 1
                logger.debug("brain cache hit (%d total)", self.cache_hits)
                self.costs.record(entry.usage.get("model", first_model),
                                  0, 0, tier=Tier.LOCAL.value, cached=True)
                return BrainResponse(text=entry.text,
                                     tier=Tier.LOCAL,
                                     model=entry.usage.get("model",
                                                           first_model),
                                     elapsed=0.0)

        now = time.monotonic()
        errors: dict[str, str] = {}
        for tier in order:
            if not self._tier_available(tier):
                errors[tier.value] = "tier disabled"
                continue
            state = self._state[tier]
            if force is None and state.cooldown_until > now:
                errors[tier.value] = (f"in cooldown after {state.consecutive_failures} "
                                      f"failures (last: {state.last_error})")
                continue
            if tier is Tier.LOCAL and self.resource_guard is not None:
                try:
                    guard_ok = await self.resource_guard()
                except Exception as exc:  # noqa: BLE001 — guard must never kill chat
                    guard_ok = True
                    logger.warning("resource guard errored (ignoring): %s", exc)
                if not guard_ok:
                    errors[tier.value] = "resource guard: not enough free VRAM"
                    logger.info("local tier skipped: low VRAM")
                    continue
            if tier is Tier.REMOTE and self.budget_guard is not None:
                try:
                    within_budget = await self.budget_guard()
                except Exception as exc:  # noqa: BLE001 — guard must never kill chat
                    within_budget = True
                    logger.warning("budget guard errored (ignoring): %s", exc)
                if not within_budget:
                    errors[tier.value] = ("daily spend budget exhausted — "
                                          "remote tier paused")
                    logger.warning("remote tier skipped: budget exhausted")
                    continue
            try:
                started = time.monotonic()
                if tier is Tier.LOCAL:
                    text = await self.local.chat(messages,
                                                 temperature=temperature)
                else:
                    text = await self.remote.chat(messages,
                                                  temperature=temperature)
                state.requests += 1
                state.served += 1
                state.consecutive_failures = 0
                state.cooldown_until = 0.0
                model = self.local.model if tier is Tier.LOCAL \
                    else self.remote.model
                usage = getattr(self.local if tier is Tier.LOCAL
                                else self.remote, "last_usage", {}) or {}
                self.costs.record(model,
                                  int(usage.get("prompt_tokens") or 0),
                                  int(usage.get("completion_tokens") or 0),
                                  tier=tier.value)
                if cache_key is not None:
                    self.cache.put(cache_key, text, {
                        "model": model,
                        "total_tokens": int(usage.get("total_tokens") or 0)})
                return BrainResponse(text=text, tier=tier, model=model,
                                     elapsed=time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 — any tier error fails over
                state.failures += 1
                state.consecutive_failures += 1
                state.last_error = f"{type(exc).__name__}: {exc}"
                errors[tier.value] = state.last_error
                logger.warning("tier %s failed (%d in a row): %s",
                               tier.value, state.consecutive_failures, exc)
                if state.consecutive_failures >= self._fallback_after:
                    state.cooldown_until = time.monotonic() + self._cooldown_seconds
                    logger.warning("tier %s entering %.0fs cooldown",
                                   tier.value, self._cooldown_seconds)
                if force is not None:
                    raise
        raise BrainUnavailable(errors)

    async def chat_stream(self, messages: list[dict[str, str]],
                          force: Tier | None = None):
        """Streaming chat: yields text deltas from the first tier that
        starts producing. A tier that fails *before* its first chunk is
        skipped like in :meth:`chat` (failover); a failure after output
        has begun propagates — partial answers are not silently re-run.

        Cache is not consulted: streamed answers are consumed
        incrementally and repeated prompts stay rare on this path.
        """
        order = [force] if force else [Tier.LOCAL, Tier.REMOTE]
        now = time.monotonic()
        errors: dict[str, str] = {}
        for tier in order:
            if not self._tier_available(tier):
                errors[tier.value] = "tier disabled"
                continue
            state = self._state[tier]
            if force is None and state.cooldown_until > now:
                errors[tier.value] = (f"in cooldown after {state.consecutive_failures} "
                                      f"failures (last: {state.last_error})")
                continue
            if tier is Tier.LOCAL and self.resource_guard is not None:
                try:
                    guard_ok = await self.resource_guard()
                except Exception:  # noqa: BLE001 — guard must never kill chat
                    guard_ok = True
                if not guard_ok:
                    errors[tier.value] = "resource guard: not enough free VRAM"
                    continue
            if tier is Tier.REMOTE and self.budget_guard is not None:
                try:
                    within_budget = await self.budget_guard()
                except Exception:  # noqa: BLE001 — guard must never kill chat
                    within_budget = True
                if not within_budget:
                    errors[tier.value] = ("daily spend budget exhausted — "
                                          "remote tier paused")
                    continue
            client = self.local if tier is Tier.LOCAL else self.remote
            model = client.model
            started = time.monotonic()
            produced = 0

            def _record_cost() -> None:
                # runs in finally: once the final chunk lands OR the
                # consumer abandons / the stream dies mid-flight, the
                # call still shows up in the ledger (usage may be partial)
                if produced == 0:
                    return
                usage = getattr(client, "last_usage", {}) or {}
                self.costs.record(model,
                                  int(usage.get("prompt_tokens") or 0),
                                  int(usage.get("completion_tokens") or 0),
                                  tier=tier.value)

            try:
                async for delta in client.chat_stream(messages):
                    if produced == 0:
                        state.requests += 1
                        state.served += 1
                        state.consecutive_failures = 0
                        state.cooldown_until = 0.0
                    produced += 1
                    yield delta
                logger.debug("streamed %d chunks from %s in %.1fs",
                             produced, model, time.monotonic() - started)
                return
            except Exception as exc:  # noqa: BLE001 — failover until first chunk
                if produced:
                    raise
                state.failures += 1
                state.consecutive_failures += 1
                state.last_error = f"{type(exc).__name__}: {exc}"
                errors[tier.value] = state.last_error
                logger.warning("stream tier %s failed pre-chunk: %s",
                               tier.value, exc)
                if state.consecutive_failures >= self._fallback_after:
                    state.cooldown_until = time.monotonic() + self._cooldown_seconds
                if force is not None:
                    raise
            finally:
                _record_cost()
        raise BrainUnavailable(errors)

    # ----------------------------------------------------------------- health
    async def health(self) -> dict:
        t0 = time.perf_counter()
        local_ok, detail = (False, "disabled") if not self.local_enabled \
            else await self.local.healthy()
        local_ms = round((time.perf_counter() - t0) * 1000, 1)
        t1 = time.perf_counter()
        remote_configured = bool(self.vault.get("GLM_API_KEY")) and self.remote_enabled
        remote_ms = round((time.perf_counter() - t1) * 1000, 1)
        return {
            "local": {"ok": local_ok, "detail": detail,
                      "duration_ms": local_ms,
                      "model": self.local.model if self.local_enabled else None},
            "remote": {"ok": remote_configured, "detail":
                       "ok" if remote_configured else "GLM_API_KEY not set or disabled",
                       "duration_ms": remote_ms,
                       "model": self.remote.model if self.remote_enabled else None},
            "stats": {tier.value: {
                "requests": st.requests, "failures": st.failures,
                "consecutive_failures": st.consecutive_failures,
                "cooldown_active": st.cooldown_until > time.monotonic(),
            } for tier, st in self._state.items()},
        }

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict[str, dict]:
        return {tier.value: {"requests": st.requests, "served": st.served,
                             "failures": st.failures}
                for tier, st in self._state.items()}

    def tier_details(self) -> dict[str, dict]:
        """Per-tier counters including the last error, for /api/adapters."""
        now = time.monotonic()
        return {tier.value: {
            "requests": st.requests, "served": st.served,
            "failures": st.failures,
            "consecutive_failures": st.consecutive_failures,
            "cooldown_active": st.cooldown_until > now,
            "cooldown_remaining_s": round(max(0.0, st.cooldown_until - now),
                                          1),
            "last_error": st.last_error,
        } for tier, st in self._state.items()}

    def cost_report(self) -> dict:
        """Cost ledger snapshot: every chat (hit or miss) is recorded."""
        return self.costs.report()

    def cache_stats(self) -> dict:
        """Response-cache snapshot for the dashboard: hits, misses,
        hit rate, evictions, and the bridge's own hit counter."""
        return {**self.cache.snapshot(), "bridge_hits": self.cache_hits}

    def _tier_available(self, tier: Tier) -> bool:
        return {Tier.LOCAL: self.local_enabled,
                Tier.REMOTE: self.remote_enabled}[tier]

    # -------------------------------------------------------------- embedding
    async def embed(self, text: str) -> list[float] | None:
        """Best-effort embedding via Ollama; None lets memory fall back.

        Any failure (unreachable server, transport misconfig) degrades to
        the caller's fallback — recall must never crash over embeddings."""
        if not self.local_enabled:
            return None
        try:
            return await self.local.embed(
                text, model=self.cfg.get("memory.embedding_model"))
        except Exception as exc:   # noqa: BLE001 — best-effort by contract
            logger.debug("embedding fell back to hashing embedder: %s", exc)
            return None

    async def close(self) -> None:
        await asyncio.gather(self.local.close(), self.remote.close(),
                             return_exceptions=True)
