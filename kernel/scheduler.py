"""Task scheduler — the daemon's autonomous work loop.

Tasks live in SQLite (see ``kernel.memory``). The loop polls for due tasks
every ``agent.poll_seconds``, claims them atomically (``status =
'pending' -> 'running'`` guarded by a conditional UPDATE), runs each as a
ReAct episode under a concurrency semaphore, and reschedules on completion:
one-shot tasks end, ``interval_seconds`` tasks recur, ``daily_at`` tasks run
once per day. Recurring tasks auto-disable after repeated failures. A task
with ``depends_on`` (task ids) stays blocked until every dependency has
settled to ``done``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from kernel.bus import EventBus
from kernel.logging import get_logger
from kernel.memory import Memory
from kernel.react import ReactAgent

logger = get_logger("scheduler")


class Scheduler:
    def __init__(self, memory: Memory, agent_factory, bus: EventBus,
                 poll_seconds: float = 5.0, concurrency: int = 2):
        self.memory = memory
        self._agent_factory = agent_factory   # () -> ReactAgent
        self.bus = bus
        self.poll_seconds = poll_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._stopping = asyncio.Event()
        self._inflight: set[asyncio.Task] = set()
        self._blocked: dict[int, list[int]] = {}
        self.stats = {"episodes_done": 0, "episodes_failed": 0,
                      "blocked_tasks": 0}

    # ------------------------------------------------------------------- loop
    async def run_forever(self) -> None:
        recovered = await self.memory.reset_stale_running()
        if recovered:
            logger.info("recovered %d stale running task(s) from a previous boot",
                        recovered)
        logger.info("scheduler started (poll=%ss concurrency=%d)",
                    self.poll_seconds, self._semaphore._value)  # noqa: SLF001
        while not self._stopping.is_set():
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                logger.exception("scheduler tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stopping.wait(),
                                       timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
        if self._inflight:
            logger.info("scheduler stopping; waiting for %d episode(s)",
                        len(self._inflight))
            await asyncio.gather(*self._inflight, return_exceptions=True)

    async def _tick(self) -> None:
        await self._publish_block_changes()
        due = await self.memory.due_tasks(limit=5)
        for task in due:
            claimed = await self.memory.mark_task_running(task["id"])
            if not claimed:
                continue
            runner = asyncio.create_task(self._run_task(task))
            self._inflight.add(runner)
            runner.add_done_callback(self._inflight.discard)

    async def _publish_block_changes(self) -> None:
        """Emit task_blocked / task_released transitions on the
        ``scheduler`` channel so /ws and the dashboard can show them."""
        try:
            blocked = await self.memory.blocked_pending_tasks(limit=25)
        except Exception as exc:   # noqa: BLE001 — events are best-effort
            logger.warning("blocked-task scan failed: %r", exc)
            return
        current = {task["id"]: task["blocked_by"] for task in blocked}
        self.stats["blocked_tasks"] = len(current)
        for task_id, deps in current.items():
            if task_id not in self._blocked:
                self.bus.publish("scheduler", {
                    "event": "task_blocked", "task_id": task_id,
                    "blocked_by": deps})
        for task_id in set(self._blocked) - set(current):
            self.bus.publish("scheduler", {
                "event": "task_released", "task_id": task_id})
        self._blocked = current

    async def _run_task(self, task: dict[str, Any]) -> None:
        task_id = task["id"]
        goal = task["goal"]
        source = task.get("source", "scheduler")
        started = time.monotonic()
        async with self._semaphore:
            logger.info("task %s starting: %s", task_id, goal[:120])
            try:
                agent: ReactAgent = self._agent_factory()
                result = await agent.run(goal, source=source)
                success = result.status == "done"
                transient = (not success
                             and "all LLM tiers failed" in result.answer)
                if success:
                    self.stats["episodes_done"] += 1
                else:
                    self.stats["episodes_failed"] += 1
                await self.memory.finish_task(task_id, success)
                if transient:
                    self.stats["retries"] = self.stats.get("retries", 0) + 1
                    backoff = min(300, 30 * 2 ** min(
                        int(task.get("consecutive_failures", 0)), 4))
                    logger.info("task %s transient failure — requeued in %ds",
                                task_id, backoff)
                    await self._memory_shift_next_run(task_id, backoff)
                logger.info("task %s %s in %.1fs", task_id, result.status,
                            time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 — record and reschedule
                logger.exception("task %s crashed", task_id)
                self.stats["episodes_failed"] += 1
                await self.memory.finish_task(task_id, success=False)

    async def _memory_shift_next_run(self, task_id: int,
                                     delay_seconds: float) -> None:
        """Push a one-shot task's next run out for a retry."""
        rows = await self.memory.list_tasks(task_id=task_id)
        if not rows:
            return
        row = rows[0]
        if row.get("interval_seconds") or row.get("daily_at"):
            return   # recurring tasks already reschedule via finish_task
        await self.memory.retry_one_shot(task_id, time.time() + delay_seconds)

    # ---------------------------------------------------------------- control
    def stop(self) -> None:
        self._stopping.set()

    async def submit(self, goal: str, source: str = "operator", **kwargs) -> int:
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        task_id = await self.memory.submit_task(goal.strip(), source, **kwargs)
        self.bus.publish("audit", {"actor": f"scheduler:{source}",
                                   "action": "task.submit",
                                   "detail": f"#{task_id} {goal[:200]}"})
        # wake the loop so one-shot tasks start immediately
        self._stopping.set()
        self._stopping = asyncio.Event()
        return task_id
