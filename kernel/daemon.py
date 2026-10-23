"""AgentDaemon — the 24/7 asyncio composition root.

Builds and supervises every subsystem:

- vault, policy, executor (OpenShell)
- brain (dual-tier) with a VRAM resource guard
- memory (SQLite + vectors), tool registry, skills, ReAct agent
- scheduler loop, heartbeat loop, audit persistence, log persistence
- web dashboard + Telegram gateway (interface/, imported lazily)

Every long-running task is wrapped in a supervisor that restarts it with
backoff on crash — a 24/7 daemon must survive its own bugs.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from brain.bridge import Brain
from brain.cost import CostTracker
from kernel.bus import EventBus
from kernel.clock import Clock
from kernel.config import Config
from kernel.health import HealthRegistry, HealthStatus, Status
from kernel.logging import get_logger, setup_logging
from kernel.memory import Memory
from kernel.metrics import REGISTRY as metrics
from kernel.react import ReactAgent
from kernel.scheduler import Scheduler
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor
from openshell.profiles import build_policy
from memory_search.graph_store import GraphStore
from security.approval import ApprovalQueue, request_to_dict
from security.quarantine import QuarantineStore
from tools.graph_tools import register_tools as register_graph_tools
from tools.registry import ToolRegistry
from tools import sysmon as sysmon_tools
from tools import skillforge as skillforge_tools
from tools import stdlib_tools
from tools import webfetch as webfetch_tools
from swarm.delegate import register_swarm_tools

logger = get_logger("daemon")


class AgentDaemon:
    def __init__(self, config: Config):
        self.cfg = config
        self.cfg.ensure_dirs()
        self.bus = EventBus()
        self.started_at = time.time()
        self._stopping = False
        self._tasks: list[asyncio.Task] = []
        self._web_runner = None

        # OpenShell
        self.vault = SecretVault(self.cfg.path("data/vault.bin"))
        setup_logging(self.cfg.get("logging.level", "INFO"),
                      self.cfg.path(self.cfg.get("logging.file",
                                                 "data/logs/sparkagent.log")),
                      bus=self.bus, redactor=self.vault.redact)
        profile = self.cfg.get("openshell.profile", "standard")
        self.policy = build_policy(
            profile, self.cfg.sandbox_root, self.cfg.root,
            allowed_programs=self.cfg.get("openshell.allowed_programs", []))
        self.executor = SafeExecutor(
            self.policy, self.vault, self.bus,
            timeout=float(self.cfg.get("openshell.timeout", 60)),
            max_output_bytes=int(self.cfg.get("openshell.max_output_bytes",
                                              131072)),
            execs_per_minute=float(self.cfg.get("openshell.execs_per_minute",
                                                0.0)))

        # Security services
        self.approvals = ApprovalQueue(
            ttl_seconds=float(self.cfg.get("security.approval_ttl", 3600)),
            clock=Clock(),
            on_change=lambda request: self.bus.publish(
                "logs", f"[approval] {request.status} {request.kind}: "
                        f"{request.summary[:100]}"))
        self.quarantine = QuarantineStore(self.cfg.root / "data" / "quarantine")
        self.health = HealthRegistry()

        # Brain + memory
        self.costs = CostTracker()
        daily_budget = float(self.cfg.get("brain.daily_budget_usd", 5.0))

        async def _budget_guard() -> bool:
            return self.costs.within_budget(daily_budget)

        self.brain = Brain(self.cfg, self.vault, self.bus,
                           resource_guard=self._vram_guard,
                           budget_guard=_budget_guard)
        self.memory = Memory(self.cfg.db_path,
                             embedder_fn=self.brain.embed,
                             embed_dim=int(self.cfg.get("memory.embed_dim", 384)),
                             recall_k=int(self.cfg.get("memory.recall_k", 5)),
                             retention_days=int(self.cfg.get("memory.retention_days",
                                                             30)))

        # Tools
        self.registry = ToolRegistry(self.bus)
        sysmon_tools.register_tools(self.registry, self.executor)
        self.fetcher = webfetch_tools.WebFetcher(
            allowed_ports=self.cfg.get("tools.webfetch.allowed_ports", [80, 443]),
            max_bytes=int(self.cfg.get("tools.webfetch.max_bytes", 2097152)),
            timeout=float(self.cfg.get("tools.webfetch.timeout", 30)),
            max_chars=int(self.cfg.get("tools.webfetch.max_chars", 6000)),
            vault=self.vault,
            quarantine=self.quarantine,
            guard_enabled=bool(self.cfg.get("tools.webfetch.prompt_guard",
                                            True)))
        webfetch_tools.register_tools(self.registry, self.fetcher)
        stdlib_tools.register_tools(self.registry, self.approvals)
        register_swarm_tools(self.registry, self.brain)
        self.entity_graph = GraphStore()
        loaded_edges = self.entity_graph.load(self.cfg.root / "data" /
                                              "graph.json")
        if loaded_edges:
            logger.info("entity graph restored: %d edges", loaded_edges)
        register_graph_tools(self.registry, self.entity_graph)
        self.forge = skillforge_tools.SkillForge(
            self.cfg.skills_dir, self.registry, self.policy, self.executor,
            self.bus, self.fetcher,
            autonomous=bool(self.cfg.get("tools.skillforge.autonomous",
                                         False)),
            exec_timeout=float(self.cfg.get("tools.skillforge.exec_timeout",
                                            30)),
            signing_key=self._skill_signing_key())
        skillforge_tools.register_tools(self.registry, self.forge)

        # Agent + scheduler
        self._agent = ReactAgent(self.brain, self.registry, self.memory, self.bus,
                                 self.cfg, executor=self.executor, vault=self.vault)
        self.scheduler = Scheduler(
            self.memory, lambda: self._agent, self.bus,
            poll_seconds=float(self.cfg.get("agent.poll_seconds", 5)),
            concurrency=int(self.cfg.get("agent.concurrency", 2)))

        self._snapshot: dict = {}
        self._brain_health: dict = {}

    # ------------------------------------------------------------------ guard
    async def _vram_guard(self) -> bool:
        return await sysmon_tools.vram_guard(
            self.executor, float(self.cfg.get("brain.vram_guard_mb", 1024)))

    def _skill_signing_key(self) -> bytes | None:
        """Sign skills when the vault master key is present (opt-out)."""
        if not bool(self.cfg.get("tools.skillforge.sign_skills", True)):
            return None
        import os
        master = os.environ.get("SPARKAGENT_VAULT_KEY", "").strip()
        if not master:
            return None
        from security.signatures import derive_signing_key
        return derive_signing_key(master, domain="skill")

    # ---------------------------------------------------------------- health
    def _register_health_checks(self) -> None:
        async def memory_check() -> HealthStatus:
            try:
                await self.memory.recent_episodes(limit=1)
                return HealthStatus(Status.OK, "sqlite responsive")
            except Exception as exc:  # noqa: BLE001
                return HealthStatus(Status.DOWN, str(exc))

        async def brain_check() -> HealthStatus:
            health = await self.brain.health()
            tiers_up = [name for name, info in
                        (("local", health.get("local")),
                         ("remote", health.get("remote")))
                        if info and info.get("ok")]
            if tiers_up:
                return HealthStatus(Status.OK,
                                    f"tiers up: {', '.join(tiers_up)}")
            return HealthStatus(Status.DEGRADED, "no LLM tier available")

        async def executor_check() -> HealthStatus:
            stats = self.executor.registry.stats()
            failed = stats.get("failed", 0)
            completed = stats.get("completed", 0)
            if completed and failed / completed > 0.5:
                return HealthStatus(Status.DEGRADED,
                                    f"{failed}/{completed} runs failed")
            return HealthStatus(Status.OK,
                                f"{stats.get('live', 0)} live / "
                                f"{completed} completed")

        self.health.register("memory", memory_check)
        self.health.register("brain", brain_check)
        self.health.register("executor", executor_check)

    # ----------------------------------------------------------------- start
    async def start(self) -> None:
        self.bus.bind_loop(asyncio.get_running_loop())
        await self.memory.connect()
        loaded = self.forge.load_persisted()
        logger.info("skills loaded: %s", loaded)
        await self.memory.audit("daemon", "boot", self.cfg.get("agent.name"))
        self._register_health_checks()

        self._spawn("scheduler", self.scheduler.run_forever)
        self._spawn("heartbeat", self._heartbeat_loop)
        self._spawn("audit_persist", self._audit_persist_loop)
        self._spawn("housekeeping", self._housekeeping_loop)

        if self.cfg.get("interface.web.enabled", True):
            self._spawn("web", self._run_web)
        if self.cfg.get("interface.telegram.enabled", False) and \
                self.vault.get("TELEGRAM_BOT_TOKEN"):
            self._spawn("telegram", self._run_telegram)
        elif self.cfg.get("interface.telegram.enabled", False):
            logger.warning("telegram enabled but TELEGRAM_BOT_TOKEN is not set")
        logger.info("SparkAgent daemon up (uptime reference %s)",
                    time.strftime("%Y-%m-%d %H:%M:%S"))

    def _spawn(self, name: str, factory) -> None:
        async def supervised() -> None:
            backoff = 5.0
            while not self._stopping:
                try:
                    await factory()
                    if self._stopping:
                        return
                    logger.warning("%s loop exited; restarting in %.0fs",
                                   name, backoff)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — supervise everything
                    logger.exception("%s crashed (%s); restarting in %.0fs",
                                     name, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)
        self._tasks.append(asyncio.create_task(supervised(), name=name))

    # ----------------------------------------------------------------- loops
    async def _heartbeat_loop(self) -> None:
        interval = float(self.cfg.get("agent.heartbeat_seconds", 30))
        while not self._stopping:
            try:
                self._snapshot = await sysmon_tools.system_snapshot(self.executor)
                gpu = self._snapshot.get("gpu", {})
                if gpu.get("available") and gpu.get("gpus"):
                    for index, card in enumerate(gpu["gpus"]):
                        metrics.gauge(f"gpu_{index}_utilization_pct",
                                      card.get("utilization_pct") or 0)
                        metrics.gauge(f"gpu_{index}_vram_free_mb",
                                      card.get("vram_free_mb") or 0)
                metrics.gauge("tasks_done", self.scheduler.stats["episodes_done"])
                metrics.gauge("tasks_failed",
                              self.scheduler.stats["episodes_failed"])
                metrics.incr("heartbeat_total")
                try:
                    self._brain_health = await self.brain.health()
                except Exception as exc:  # noqa: BLE001
                    self._brain_health = {"error": str(exc)}
                self.bus.publish("status", {"snapshot": self._snapshot,
                                            "brain": self._brain_health,
                                            "uptime_s": int(time.time() -
                                                            self.started_at)})
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat failed: %s", exc)
            await asyncio.sleep(interval)

    async def _audit_persist_loop(self) -> None:
        queue = self.bus.subscribe("audit")
        try:
            while not self._stopping:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    await self.memory.audit(event.get("actor", "?"),
                                            event.get("action", "?"),
                                            event.get("detail"))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("audit persist failed: %s", exc)
        finally:
            self.bus.unsubscribe("audit", queue)

    async def _housekeeping_loop(self) -> None:
        while not self._stopping:
            await asyncio.sleep(6 * 3600)
            try:
                pruned = await self.memory.housekeeping()
                if any(pruned.values()):
                    logger.info("housekeeping pruned: %s", pruned)
                digests = await self._consolidate_episodes()
                if digests:
                    logger.info("consolidated %d episode(s) into memory",
                                digests)
                saved = self.entity_graph.save(self.cfg.root / "data" /
                                               "graph.json")
                logger.debug("entity graph persisted: %d edges", saved)
            except Exception as exc:  # noqa: BLE001
                logger.warning("housekeeping failed: %s", exc)

    async def _consolidate_episodes(self, batch: int = 30) -> int:
        """Distill finished episodes into one compact memory per episode."""
        from datetime import datetime, timedelta
        from memory_search.summarizer import consolidate
        since = (datetime.now() - timedelta(
            days=int(self.cfg.get("memory.retention_days", 30)))
        ).isoformat(timespec="seconds")
        episodes = await self.memory.episodes_without_digest(since,
                                                             limit=batch)
        if not episodes:
            return 0
        digest_text = consolidate(episodes,
                                  header="Episode consolidation")
        await self.memory.remember(digest_text, kind="digest",
                                   key=f"digest:{episodes[0]['id']}-"
                                       f"{episodes[-1]['id']}")
        # mark each source episode as digested by its own key
        for episode in episodes:
            await self.memory.remember(
                f"[digested] {episode['goal'][:200]}",
                kind="digest-marker", key=f"episode:{episode['id']}")
        return len(episodes)

    async def _run_web(self) -> None:
        from interface.web import build_web_app  # lazy: interface lands later
        app = build_web_app(self)
        from aiohttp import web
        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        site = web.TCPSite(self._web_runner,
                           self.cfg.get("interface.web.host", "127.0.0.1"),
                           int(self.cfg.get("interface.web.port", 8788)))
        await site.start()
        logger.info("web dashboard on http://%s:%s",
                    self.cfg.get("interface.web.host", "127.0.0.1"),
                    self.cfg.get("interface.web.port", 8788))
        while not self._stopping:
            await asyncio.sleep(3600)

    async def _run_telegram(self) -> None:
        from interface.telegram import TelegramGateway  # lazy
        gateway = TelegramGateway(
            self, self.vault.require("TELEGRAM_BOT_TOKEN"),
            allowed_chat_ids=self.cfg.get(
                "interface.telegram.allowed_chat_ids", []))
        await gateway.run_forever()

    # ------------------------------------------------------------------ api
    async def submit_task(self, goal: str, source: str = "operator", **kw) -> int:
        return await self.scheduler.submit(goal, source=source, **kw)

    async def run_once(self, goal: str, source: str = "operator"):
        return await self._agent.run(goal, source=source)

    def status(self) -> dict:
        return {
            "agent": self.cfg.get("agent.name"),
            "version": "0.2.0",
            "uptime_s": int(time.time() - self.started_at),
            "system": self._snapshot,
            "brain": self._brain_health or self.brain.stats(),
            "scheduler": dict(self.scheduler.stats),
            "tools": self.registry.names(),
            "skills_pending": sorted(self.forge.pending),
            "approvals_pending": [request_to_dict(r) for r in
                                  self.approvals.pending()],
            "guard_stats": dict(self.fetcher.guard_stats),
            "executor": self.executor.registry.stats(),
            "sandbox_profile": self.cfg.get("openshell.profile", "standard"),
            "vault_unlocked": self.vault.unlocked,
        }

    # ------------------------------------------------------------------ stop
    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        logger.info("daemon shutting down…")
        try:
            self.entity_graph.save(self.cfg.root / "data" / "graph.json")
        except OSError as exc:
            logger.warning("entity graph save failed: %s", exc)
        self.scheduler.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._web_runner is not None:
            await self._web_runner.cleanup()
        await asyncio.gather(self.brain.close(), self.fetcher.close(),
                             return_exceptions=True)
        await self.memory.close()
        logger.info("daemon stopped")
