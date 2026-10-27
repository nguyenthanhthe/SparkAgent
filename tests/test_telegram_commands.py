import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from interface.telegram import TelegramGateway


class FakeDaemon:
    """Just enough daemon for command unit tests."""

    def __init__(self):
        from kernel.clock import FakeClock
        from security.approval import ApprovalQueue

        class FakeForge:
            def list_skills(self):
                return [{"name": "word_count", "status": "active"},
                        {"name": "disk_tool", "status": "pending_approval"}]

            def approve(self, name, source):
                if name != "disk_tool":
                    raise KeyError(name)
                return {"skill": name, "status": "active"}

        class FakeMemory:
            async def list_tasks(self, limit=10):
                return [{"id": 1, "status": "pending", "goal": "g",
                         "enabled": 1}]

            async def blocked_pending_tasks(self, limit=50):
                return [{"id": 1, "goal": "g", "blocked_by": [7]}]

            async def recall(self, query, k=5, kinds=None):
                return []

            async def recent_audit(self, limit=15):
                return [{"created_at": "2026-10-24T10:00:00", "actor":
                         "executor", "action": "exec.start",
                         "detail": "python -c print(1)"},
                        {"created_at": "2026-10-24T10:00:05", "actor":
                         "operator", "action": "memory.forget",
                         "detail": "key=temp"}]

        self.forge = FakeForge()
        self.memory = FakeMemory()
        self.approvals = ApprovalQueue(clock=FakeClock())

        class FakeHealth:
            async def check_all(self):
                return {"status": "ok", "checks": []}

        self.health = FakeHealth()

        class Vault:
            def redact(self, text):
                return text

        self.vault = Vault()

    def status(self):
        return {"agent": "sparkagent", "version": "0.2.0", "uptime_s": 300,
                "brain": {"local": {"ok": True, "model": "nemotron"},
                          "remote": {"ok": False, "detail": "no key"}},
                "system": {"gpu": {"available": False}},
                "scheduler": {"episodes_done": 2, "episodes_failed": 1},
                "quarantine": {"items": 3, "bytes": 900}}

    async def submit_task(self, goal, source, **kw):
        return 7


def make_gateway():
    return TelegramGateway(FakeDaemon(), token="unit-token",
                           allowed_chat_ids=[42])


class TelegramCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _command(self, text, gateway=None):
        gateway = gateway or make_gateway()
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 42}, "text": text})
            return send.call_args[0][1]

    async def test_health_reports_subsystems(self):
        gateway = make_gateway()
        reply = await self._command("/health", gateway)
        self.assertIn("overall: ok", reply)
        self.assertIn("0/0 checks ok", reply)

    async def test_status(self):
        reply = await self._command("/status")
        self.assertIn("uptime: 5 min", reply)
        self.assertIn("nemotron — ok", reply)
        self.assertIn("episodes: 2 done / 1 failed", reply)
        self.assertIn("quarantine: 3 item(s)", reply)

    async def test_status_cache_line_when_present(self):
        gateway = make_gateway()

        class FakeBrain:
            def cache_stats(self):
                return {"hits": 3, "misses": 7, "hit_rate": 0.3}
        gateway.daemon.brain = FakeBrain()
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 42}, "text": "/status"})
            reply = send.call_args[0][1]
        self.assertIn("cache: 3 hit(s) / 10 (30%)", reply)

    async def test_pending_lists_skills_and_approvals(self):
        gateway = make_gateway()
        gateway.daemon.approvals.submit("question", "reboot the server?")
        reply = await self._command("/pending", gateway)
        self.assertIn("[skill] disk_tool", reply)
        self.assertIn("[question]", reply)

    async def test_approve_skill_by_name(self):
        reply = await self._command("/approve disk_tool")
        self.assertIn("disk_tool: active", reply)

    async def test_approve_approval_by_id(self):
        gateway = make_gateway()
        request = gateway.daemon.approvals.submit("spend", "$10 budget")
        reply = await self._command(f"/approve {request.id}", gateway)
        self.assertIn("approved", reply)

    async def test_deny_approval(self):
        gateway = make_gateway()
        request = gateway.daemon.approvals.submit("command", "rm temp")
        reply = await self._command(f"/deny {request.id}", gateway)
        self.assertIn("denied", reply)

    async def test_deny_decided_request_errors(self):
        gateway = make_gateway()
        request = gateway.daemon.approvals.submit("generic", "x")
        gateway.daemon.approvals.deny(request.id)
        reply = await self._command(f"/deny {request.id}", gateway)
        self.assertIn("error", reply)

    async def test_plain_text_submits_task(self):
        reply = await self._command("check the gpu load hourly")
        self.assertIn("Task #7 submitted", reply)

    async def test_unauthorized_chat_ignored(self):
        gateway = make_gateway()
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 999},
                                   "text": "/status"})
            send.assert_not_called()

    async def test_mem_empty(self):
        reply = await self._command("/mem nothing matches")
        self.assertIn("no memories", reply)

    async def test_mem_kind_filter_passed_through(self):
        gateway = make_gateway()
        seen = {}

        async def recall(query, k=5, kinds=None):
            seen["kinds"] = kinds
            return []
        gateway.daemon.memory.recall = recall
        with mock.patch.object(TelegramGateway, "_send"):
            await gateway._handle({"chat": {"id": 42},
                                   "text": "/mem thermals --kind fact"})
        self.assertEqual(seen["kinds"], ["fact"])

    async def test_audit_lists_redacted_rows(self):
        reply = await self._command("/audit")
        self.assertIn("executor exec.start", reply)
        self.assertIn("print(1)", reply)

    async def test_audit_actor_filter(self):
        reply = await self._command("/audit --actor operator")
        self.assertIn("memory.forget", reply)
        self.assertNotIn("exec.start", reply)

    async def test_help_lists_new_commands(self):
        reply = await self._command("/help")
        self.assertIn("/pending", reply)
        self.assertIn("/deny", reply)

    async def test_help_groups_by_audience(self):
        reply = await self._command("/help")
        self.assertIn("operator:", reply)
        self.assertIn("agent:", reply)
        self.assertLess(reply.index("operator:"), reply.index("agent:"))
        # approval commands stay in the operator section, tools in agent
        self.assertLess(reply.index("/deny"), reply.index("agent:"))
        self.assertGreater(reply.index("/db"), reply.index("agent:"))


class TelegramTasksLimitTests(unittest.IsolatedAsyncioTestCase):
    async def _reply_with_limit(self) -> int:
        gateway = make_gateway()
        seen = {}

        async def list_tasks(limit=10):
            seen["limit"] = limit
            return []
        gateway.daemon.memory.list_tasks = list_tasks
        with mock.patch.object(TelegramGateway, "_send"):
            await gateway._handle({"chat": {"id": 42},
                                   "text": "/tasks --limit 25"})
        return seen["limit"]

    async def test_limit_passed_through(self):
        self.assertEqual(await self._reply_with_limit(), 25)

    async def test_tasks_show_blockers_inline(self):
        gateway = make_gateway()
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 42}, "text": "/tasks"})
            reply = send.call_args[0][1]
        self.assertIn("#1 [pending] g", reply)
        self.assertIn("blocked by #7", reply)


class TelegramDbCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, goal TEXT,"
                     " status TEXT)")
        conn.execute("INSERT INTO tasks (goal, status) VALUES "
                     "('water plants', 'pending'),"
                     "('feed cat', 'done')")
        conn.commit()
        conn.close()
        self.gateway = make_gateway()
        self.gateway.daemon.cfg = SimpleNamespace(db_path=self.db)

    async def _command(self, text):
        with mock.patch.object(TelegramGateway, "_send") as send:
            await self.gateway._handle({"chat": {"id": 42}, "text": text})
            return send.call_args[0][1]

    async def test_db_lists_rows(self):
        reply = await self._command("/db tasks")
        self.assertIn("tasks: 2 row(s)", reply)
        self.assertIn("water plants", reply)

    async def test_db_where_filter(self):
        reply = await self._command("/db tasks status=done")
        self.assertIn("feed cat", reply)
        self.assertNotIn("water plants", reply)

    async def test_db_no_rows(self):
        reply = await self._command("/db tasks goal=nothing")
        self.assertIn("no matching rows", reply)

    async def test_db_unknown_table(self):
        reply = await self._command("/db secrets")
        self.assertIn("error", reply)

    async def test_db_bad_term(self):
        reply = await self._command("/db tasks oops")
        self.assertIn("error", reply)

    async def test_db_usage(self):
        reply = await self._command("/db")
        self.assertIn("usage: /db", reply)


class TelegramBlockedCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _reply_with(self, stalled):
        gateway = make_gateway()

        async def blocked_pending_tasks(limit=50):
            return stalled
        gateway.daemon.memory.blocked_pending_tasks = blocked_pending_tasks
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 42}, "text": "/blocked"})
            return send.call_args[0][1]

    async def test_blocked_lists_stalled_tasks(self):
        reply = await self._reply_with(
            [{"id": 12, "goal": "digest telemetry",
              "blocked_by": [7, 9]}])
        self.assertIn("#12 blocked by #7, #9", reply)
        self.assertIn("digest telemetry", reply)

    async def test_blocked_empty(self):
        reply = await self._reply_with([])
        self.assertIn("no dependency-stalled", reply)

    async def test_blocked_limit_passthrough(self):
        gateway = make_gateway()
        seen = {}

        async def blocked_pending_tasks(limit=50):
            seen["limit"] = limit
            return []
        gateway.daemon.memory.blocked_pending_tasks = blocked_pending_tasks
        with mock.patch.object(TelegramGateway, "_send"):
            await gateway._handle({"chat": {"id": 42},
                                   "text": "/blocked --limit 7"})
        self.assertEqual(seen["limit"], 7)


class TelegramSkillsCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _reply_with(self, skills):
        gateway = make_gateway()
        gateway.daemon.forge.list_skills = lambda: skills
        with mock.patch.object(TelegramGateway, "_send") as send:
            await gateway._handle({"chat": {"id": 42}, "text": "/skills"})
            return send.call_args[0][1]

    async def test_pending_skills_come_first_with_hint(self):
        reply = await self._reply_with(
            [{"name": "word_count", "status": "active"},
             {"name": "disk_tool", "status": "pending_approval"}])
        self.assertLess(reply.index("/approve"), reply.index("word_count"))
        self.assertIn("disk_tool", reply)

    async def test_no_pending_shows_plain_list(self):
        reply = await self._reply_with(
            [{"name": "word_count", "status": "active"}])
        self.assertNotIn("/approve", reply)
        self.assertIn("word_count — active", reply)

    async def test_empty(self):
        reply = await self._reply_with([])
        self.assertIn("(no skills)", reply)

    async def test_long_list_truncated_with_hint(self):
        reply = await self._reply_with(
            [{"name": f"skill_{i:02d}", "status": "active"}
             for i in range(25)])
        self.assertIn("…and 5 more", reply)
        self.assertIn("skill_19", reply)
        self.assertNotIn("skill_24", reply)


class TelegramBackupCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from ops.backup import create_backup
        self.root = Path(tempfile.mkdtemp())
        data = self.root / "data"
        data.mkdir()
        (data / "sparkagent.db").write_bytes(b"x")
        create_backup(data, self.root / "backups", tag="nightly")
        self.gateway = make_gateway()
        self.gateway.daemon.cfg = SimpleNamespace(
            root=self.root,
            get=lambda dotted, default=None: default)

    async def _command(self, text):
        with mock.patch.object(TelegramGateway, "_send") as send:
            await self.gateway._handle({"chat": {"id": 42}, "text": text})
            return send.call_args[0][1]

    async def test_backup_lists_newest(self):
        reply = await self._command("/backup")
        self.assertIn("sparkagent-backup-", reply)
        self.assertIn("nightly", reply)
        self.assertIn("old", reply)

    async def test_backup_empty_dir(self):
        import shutil
        shutil.rmtree(self.root / "backups")
        (self.root / "backups").mkdir()
        reply = await self._command("/backup")
        self.assertIn("no backups", reply)

    async def test_backup_verify_flag(self):
        reply = await self._command("/backup --verify")
        self.assertIn("verify: newest ok", reply)


if __name__ == "__main__":
    unittest.main()
