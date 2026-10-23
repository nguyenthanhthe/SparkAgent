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
from kernel.bus import EventBus
from kernel.config import Config
from kernel.logging import get_logger, setup_logging
from kernel.memory import Memory
from kernel.react import ReactAgent
from kernel.scheduler import Scheduler
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor
from tools.registry import ToolRegistry
from tools import sysmon as sysmon_tools
from tools import skillforge as skillforge_tools
from tools import webfetch as webfetch_tools

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
        self.policy = SecurityPolicy(
            allowed_programs=self.cfg.get("openshell.allowed_programs", []),
            allowed_roots=[self.cfg.sandbox_root, self.cfg.root],
            sandbox_root=self.cfg.sandbox_root,
            allow_shell=bool(self.cfg.get("openshell.allow_shell", False)))
        self.executor = SafeExecutor(
            self.policy, self.vault, self.bus,
            timeout=float(self.cfg.get("openshell.timeout", 60)),
            max_output_bytes=int(self.cfg.get("openshell.max_output_bytes",
                                              131072)))

        # Brain + memory
        self.brain = Brain(self.cfg, self.vault, self.bus,
                           resource_guard=self._vram_guard)
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
            vault=self.vault)
        webfetch_tools.register_tools(self.registry, self.fetcher)
        self.forge = skillforge_tools.SkillForge(
            self.cfg.skills_dir, self.registry, self.policy, self.executor,
            self.bus, self.fetcher,
            autonomous=bool(self.cfg.get("tools.skillforge.autonomous", False)),
            exec_timeout=float(self.cfg.get("tools.skillforge.exec_timeout", 30)))
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

    # ----------------------------------------------------------------- start
    async def start(self) -> None:
        self.bus.bind_loop(asyncio.get_running_loop())
        await self.memory.connect()
        loaded = self.forge.load_persisted()
        logger.info("skills loaded: %s", loaded)
        await self.memory.audit("daemon", "boot", self.cfg.get("agent.name"))

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
            except Exception as exc:  # noqa: BLE001
                logger.warning("housekeeping failed: %s", exc)

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
            "version": "0.1.0",
            "uptime_s": int(time.time() - self.started_at),
            "system": self._snapshot,
            "brain": self._brain_health or self.brain.stats(),
            "scheduler": dict(self.scheduler.stats),
            "tools": self.registry.names(),
            "skills_pending": sorted(self.forge.pending),
            "vault_unlocked": self.vault.unlocked,
        }

    # ------------------------------------------------------------------ stop
    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        logger.info("daemon shutting down…")
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
