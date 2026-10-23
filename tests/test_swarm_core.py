import asyncio
import unittest

from swarm.blackboard import Blackboard
from swarm.mailbox import Mailbox
from swarm.protocols import AgentMessage, MessageKind, Sender


class ProtocolTests(unittest.TestCase):
    def test_message_roundtrip(self):
        original = AgentMessage(kind=MessageKind.TASK,
                                sender=Sender("planner", "planner"),
                                payload={"goal": "x"})
        restored = AgentMessage.from_dict(original.to_dict())
        self.assertEqual(restored.kind, MessageKind.TASK)
        self.assertEqual(restored.sender.name, "planner")
        self.assertEqual(restored.payload, {"goal": "x"})
        self.assertEqual(restored.id, original.id)

    def test_reply_preserves_trace(self):
        first = AgentMessage(kind=MessageKind.TASK,
                             sender=Sender("a"))
        answer = first.reply(MessageKind.RESULT, {"ok": True})
        self.assertEqual(answer.trace_id, first.trace_id)
        self.assertEqual(answer.in_reply_to, first.id)

    def test_unique_ids(self):
        ids = {AgentMessage(kind=MessageKind.INFO,
                            sender=Sender("x")).id for _ in range(50)}
        self.assertEqual(len(ids), 50)


class MailboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mailbox = Mailbox()
        self.mailbox.register("planner")
        self.mailbox.register("worker")

    async def test_deliver_and_receive(self):
        message = AgentMessage(kind=MessageKind.TASK, sender=Sender("planner"),
                               payload={"step": 1})
        self.assertTrue(self.mailbox.deliver(message, "worker"))
        received = await self.mailbox.receive("worker", timeout=1)
        self.assertEqual(received.id, message.id)

    async def test_receive_empty_timeout_returns_none(self):
        self.assertIsNone(await self.mailbox.receive("worker", timeout=0.01))

    async def test_unknown_recipient_rejected(self):
        message = AgentMessage(kind=MessageKind.INFO, sender=Sender("x"))
        self.assertFalse(self.mailbox.deliver(message, "ghost"))
        with self.assertRaises(KeyError):
            await self.mailbox.receive("ghost")

    async def test_broadcast_skips_sender(self):
        message = AgentMessage(kind=MessageKind.INFO, sender=Sender("planner"))
        delivered = self.mailbox.broadcast(message, skip="planner")
        self.assertEqual(delivered, 1)             # only worker got it
        self.assertEqual(self.mailbox.pending("planner"), 0)
        self.assertEqual(self.mailbox.pending("worker"), 1)

    async def test_overflow_drops_oldest(self):
        mailbox = Mailbox(capacity=3)
        mailbox.register("tiny")
        for index in range(5):
            mailbox.deliver(AgentMessage(kind=MessageKind.INFO,
                                         sender=Sender("x"),
                                         payload={"i": index}), "tiny")
        # drain in order: oldest two were dropped, so first seen is i=2
        seen = [mailbox.try_receive("tiny").payload["i"] for _ in range(3)]
        self.assertEqual(seen, [2, 3, 4])
        self.assertEqual(mailbox.stats()["dropped"], 2)

    async def test_try_receive(self):
        self.assertIsNone(self.mailbox.try_receive("planner"))
        message = AgentMessage(kind=MessageKind.INFO, sender=Sender("x"))
        self.mailbox.deliver(message, "planner")
        self.assertEqual(self.mailbox.try_receive("planner").id, message.id)

    async def test_receive_wakes_on_delivery(self):
        async def deliver_later():
            await asyncio.sleep(0.02)
            self.mailbox.deliver(AgentMessage(kind=MessageKind.INFO,
                                              sender=Sender("x"),
                                              payload={"wake": True}),
                                 "worker")

        task = asyncio.create_task(deliver_later())
        received = await self.mailbox.receive("worker")
        self.assertTrue(received.payload["wake"])
        await task


class BlackboardTests(unittest.TestCase):
    def test_put_get_remove(self):
        board = Blackboard()
        board.put("findings", "gpu", "RTX 4050 healthy", author="sysmon")
        self.assertEqual(board.get("findings", "gpu"), "RTX 4050 healthy")
        self.assertTrue(board.remove("findings", "gpu"))
        self.assertFalse(board.remove("findings", "gpu"))
        self.assertIsNone(board.get("findings", "gpu"))

    def test_sections_and_digest(self):
        board = Blackboard()
        board.put("findings", "a", "1")
        board.put("findings", "b", "2")
        board.put("decisions", "x", "3")
        self.assertEqual(board.sections(), ["decisions", "findings"])
        digest = board.digest()
        self.assertEqual(digest["total_entries"], 3)
        self.assertEqual(digest["sections"]["findings"], 2)

    def test_revision_increments(self):
        board = Blackboard()
        rev1 = board.put("s", "k", "v")
        rev2 = board.put("s", "k", "v2")   # overwrite also bumps
        self.assertEqual(rev2, rev1 + 1)

    def test_changes_since(self):
        board = Blackboard()
        snapshot = board.changes_since(0)
        self.assertFalse(snapshot["changed"])
        board.put("s", "k", "v")
        snapshot = board.changes_since(0)
        self.assertTrue(snapshot["changed"])
        self.assertEqual(snapshot["snapshot"]["s"]["k"], "v")

    def test_invalid_keys_rejected(self):
        board = Blackboard()
        with self.assertRaises(ValueError):
            board.put("", "k", "v")
        with self.assertRaises(ValueError):
            board.put("s", "", "v")

    def test_last_write_wins_with_provenance(self):
        board = Blackboard()
        board.put("s", "k", "first", author="worker-1")
        board.put("s", "k", "second", author="worker-2")
        self.assertEqual(board.get("s", "k"), "second")


if __name__ == "__main__":
    unittest.main()
