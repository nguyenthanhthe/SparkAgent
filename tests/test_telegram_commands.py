import unittest
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

            async def recall(self, query, k=5):
                return []

        self.forge = FakeForge()
        self.memory = FakeMemory()
        self.approvals = ApprovalQueue(clock=FakeClock())

        class Vault:
            def redact(self, text):
                return text

        self.vault = Vault()

    def status(self):
        return {"agent": "sparkagent", "version": "0.2.0", "uptime_s": 300,
                "brain": {"local": {"ok": True, "model": "nemotron"},
                          "remote": {"ok": False, "detail": "no key"}},
                "system": {"gpu": {"available": False}},
                "scheduler": {"episodes_done": 2, "episodes_failed": 1}}

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

    async def test_status(self):
        reply = await self._command("/status")
        self.assertIn("uptime: 5 min", reply)
        self.assertIn("nemotron — ok", reply)
        self.assertIn("episodes: 2 done / 1 failed", reply)

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

    async def test_help_lists_new_commands(self):
        reply = await self._command("/help")
        self.assertIn("/pending", reply)
        self.assertIn("/deny", reply)


if __name__ == "__main__":
    unittest.main()
