"""Telegram gateway — remote control of the agent.

Long-polls ``getUpdates`` (no webhook, no public port needed). Only chat
IDs in ``interface.telegram.allowed_chat_ids`` may interact; everyone else
is ignored (and logged). Commands:

    /status          daemon status summary
    /tasks           recent tasks
    /task <goal>     submit a one-shot task
    /mem <query>     semantic memory recall
    /skills          list skills
    /audit           recent audit trail (redacted)
    /db <table>      read-only database lookup (episodes, steps,
                     memories, tasks, audit)
    /pending         operator approval queue (skills + questions)
    /approve <id>    approve a pending skill or approval request
    /deny <id>       deny a pending approval request
    /help            command list

Plain text messages are submitted as one-shot tasks. All outbound messages
pass through the vault's redaction layer.
"""

from __future__ import annotations

import asyncio

import aiohttp

from kernel.logging import get_logger

logger = get_logger("telegram")

API_BASE = "https://api.telegram.org"
POLL_TIMEOUT = 25


class TelegramGateway:
    def __init__(self, daemon, token: str, allowed_chat_ids: list[int]):
        self.daemon = daemon
        self.token = token
        self.allowed = {int(chat_id) for chat_id in allowed_chat_ids}
        self._session: aiohttp.ClientSession | None = None
        self._offset = 0

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=POLL_TIMEOUT + 10))
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------- loop
    async def run_forever(self) -> None:
        session = await self._ensure_session()
        if not self.allowed:
            logger.warning("telegram gateway running with an empty allowlist — "
                           "nobody can talk to it")
        logger.info("telegram gateway polling (allowed chats: %s)",
                    sorted(self.allowed) or "none")
        while True:
            try:
                async with session.get(
                        f"{API_BASE}/bot{self.token}/getUpdates",
                        params={"timeout": POLL_TIMEOUT, "offset": self._offset,
                                "allowed_updates": '["message"]'}) as resp:
                    if resp.status == 409:
                        logger.warning("telegram 409: another getUpdates poller "
                                       "is active; retrying in 10s")
                        await asyncio.sleep(10)
                        continue
                    if resp.status != 200:
                        logger.warning("telegram getUpdates HTTP %s; retry in 5s",
                                       resp.status)
                        await asyncio.sleep(5)
                        continue
                    data = await resp.json()
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                logger.warning("telegram poll error: %s; retry in 5s", exc)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                self._offset = max(self._offset, update["update_id"] + 1)
                message = update.get("message") or {}
                try:
                    await self._handle(message)
                except Exception as exc:  # noqa: BLE001 — one message must not kill the loop
                    logger.exception("telegram handler failed: %s", exc)

    # ---------------------------------------------------------------- handler
    async def _handle(self, message: dict) -> None:
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if not text:
            return
        if chat_id not in self.allowed:
            logger.warning("telegram: ignored message from unauthorized chat %s",
                           chat_id)
            return

        redactor = self.daemon.vault.redact
        if text.startswith("/"):
            reply = await self._command(text)
        else:
            task_id = await self.daemon.submit_task(text, source="telegram")
            reply = f"Task #{task_id} submitted."
        await self._send(chat_id, redactor(reply))

    async def _command(self, text: str) -> str:
        command, _, args = text.partition(" ")
        command = command.split("@")[0].lower()
        daemon = self.daemon

        if command == "/help":
            return ("SparkAgent commands:\n"
                    "/status — daemon health\n"
                    "/health — subsystem checks\n"
                    "/tasks — recent tasks\n"
                    "/task <goal> — submit a task\n"
                    "/mem <query> — search memory\n"
                    "/skills — list skills\n"
                    "/audit — recent audit trail\n"
                    "/db <table> [col=value ...] — read-only db lookup\n"
                    "/pending — operator approval queue\n"
                    "/approve <skill or id> — approve\n"
                    "/deny <id> — deny an approval request\n"
                    "plain text — submit a task")
        if command == "/health":
            report = await daemon.health.check_all()
            lines = [f"overall: {report['status']}"]
            for check in report.get("checks", []):
                detail = f" — {check['detail'][:40]}" if check["detail"] \
                    else ""
                lines.append(f"{check['name']}: {check['status']}{detail}")
            return "\n".join(lines)
        if command == "/status":
            status = daemon.status()
            brain = status.get("brain", {})
            lines = [f"uptime: {status['uptime_s'] // 60} min"]
            for tier in ("local", "remote"):
                info = brain.get(tier) or {}
                mark = "ok" if info.get("ok") else (info.get("detail") or "down")
                lines.append(f"{tier}: {info.get('model')} — {mark}")
            gpu = (status.get("system", {}).get("gpu") or {})
            if gpu.get("available") and gpu.get("gpus"):
                g = gpu["gpus"][0]
                lines.append(f"gpu: {g['name']} {g['utilization_pct']}% "
                             f"{g['vram_used_mb']}/{g['vram_total_mb']}MB "
                             f"{g['temperature_c']}C")
            sched = status.get("scheduler", {})
            lines.append(f"episodes: {sched.get('episodes_done', 0)} done / "
                         f"{sched.get('episodes_failed', 0)} failed")
            return "\n".join(lines)
        if command == "/tasks":
            tasks = await daemon.memory.list_tasks(limit=10)
            if not tasks:
                return "(no tasks)"
            return "\n".join(
                f"#{t['id']} [{t['status'] if t['enabled'] else 'off'}] "
                f"{t['goal'][:60]}" for t in tasks)
        if command == "/task":
            if not args.strip():
                return "usage: /task <goal>"
            task_id = await daemon.submit_task(args, source="telegram")
            return f"Task #{task_id} submitted."
        if command == "/mem":
            if not args.strip():
                return "usage: /mem <query>"
            hits = await daemon.memory.recall(args, k=5)
            if not hits:
                return "(no memories found)"
            return "\n\n".join(
                f"[{h.kind}] {h.snippet or h.text[:250]}" for h in hits)
        if command == "/skills":
            skills = daemon.forge.list_skills()
            return "\n".join(f"{s['name']} — {s['status']}" for s in skills) \
                or "(no skills)"
        if command == "/audit":
            rows = await daemon.memory.recent_audit(limit=15)
            if not rows:
                return "(audit trail empty)"
            lines = []
            for row in rows:
                detail = daemon.vault.redact(row.get("detail") or "")[:60]
                lines.append(f"{row['created_at'][11:]} {row['actor']} "
                             f"{row['action']} {detail}")
            return "\n".join(lines)
        if command == "/db":
            from tools.sqlite_query import lookup
            from kernel.errors import ToolFailure
            table, _, rest = args.strip().partition(" ")
            table = table.strip().lower()
            if not table:
                return ("usage: /db <table> [col=value ...] — tables: "
                        "episodes, steps, memories, tasks, audit")
            where: dict[str, str] = {}
            limit = 10
            for token in rest.split():
                column, sep, value = token.partition("=")
                if sep and column.lower() != "limit":
                    where[column] = value
                elif column.lower() == "limit" and value.isdigit():
                    limit = int(value)
                else:
                    return f"error: bad term {token!r} (want col=value or limit=N)"
            try:
                result = await lookup(daemon.cfg.db_path, table,
                                      where=where, limit=limit)
            except ToolFailure as exc:
                return f"error: {exc}"
            rows = result.get("rows", [])
            if not rows:
                return f"({table}: no matching rows)"
            lines = [f"{table}: {len(rows)} row(s)"]
            for row in rows[:limit]:
                compact = " ".join(
                    f"{key}={str(value)[:40]}"
                    for key, value in list(row.items())[:6])
                lines.append(compact[:300])
            return "\n".join(lines)
        if command == "/pending":
            lines = []
            for skill in daemon.forge.list_skills():
                if skill["status"] == "pending_approval":
                    lines.append(f"[skill] {skill['name']}")
            for request in daemon.approvals.pending():
                lines.append(f"[{request.kind}] {request.id[:8]} "
                             f"{request.summary[:60]}")
            return "\n".join(lines) or "(nothing pending)"
        if command == "/approve":
            target = args.strip()
            if not target:
                return "usage: /approve <skill-name or approval-id>"
            # skill names are identifiers; approval ids are 12-char tokens
            skill_names = {s["name"] for s in daemon.forge.list_skills()
                           if s["status"] == "pending_approval"}
            if target in skill_names:
                result = daemon.forge.approve(target, source="operator")
                return f"skill {result['skill']}: {result['status']}"
            try:
                request = daemon.approvals.approve(target,
                                                   decided_by="telegram")
                return f"approval {request.id[:8]}: {request.status}"
            except (KeyError, ValueError) as exc:
                return f"error: {exc}"
        if command == "/deny":
            target = args.strip()
            if not target:
                return "usage: /deny <approval-id>"
            try:
                request = daemon.approvals.deny(target,
                                                decided_by="telegram")
                return f"approval {request.id[:8]}: {request.status}"
            except (KeyError, ValueError) as exc:
                return f"error: {exc}"
        return f"unknown command {command} — try /help"

    async def _send(self, chat_id: int, text: str) -> None:
        session = await self._ensure_session()
        try:
            async with session.post(
                    f"{API_BASE}/bot{self.token}/sendMessage",
                    json={"chat_id": chat_id, "text": text[:4000]}) as resp:
                if resp.status != 200:
                    logger.warning("telegram sendMessage HTTP %s: %s",
                                   resp.status, (await resp.text())[:200])
        except aiohttp.ClientError as exc:
            logger.warning("telegram send failed: %s", exc)
