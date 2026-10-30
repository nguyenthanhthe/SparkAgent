"""EventBus subscriber_count — observability for live listeners."""

import asyncio
import unittest

from kernel.bus import EventBus


class SubscriberCountTests(unittest.TestCase):
    def test_counts_total_and_per_channel(self):
        bus = EventBus()
        self.assertEqual(bus.subscriber_count(), 0)
        self.assertEqual(bus.subscriber_count("audit"), 0)

        q1 = bus.subscribe("audit")
        q2 = bus.subscribe("audit")
        q3 = bus.subscribe("logs")
        self.assertEqual(bus.subscriber_count("audit"), 2)
        self.assertEqual(bus.subscriber_count("logs"), 1)
        self.assertEqual(bus.subscriber_count(), 3)

        bus.unsubscribe("audit", q1)
        self.assertEqual(bus.subscriber_count("audit"), 1)
        self.assertEqual(bus.subscriber_count(), 2)

    def test_unsubscribe_unknown_channel_is_a_noop(self):
        bus = EventBus()
        queue: asyncio.Queue = asyncio.Queue()
        bus.unsubscribe("never-subscribed", queue)   # must not raise
        self.assertEqual(bus.subscriber_count(), 0)


class OverflowCounterTests(unittest.TestCase):
    def test_drop_oldest_overflow_is_counted(self):
        from kernel.metrics import REGISTRY
        bus = EventBus(maxsize=2)
        queue = bus.subscribe("logs")
        before = REGISTRY.counter("bus_overflow_total")
        for i in range(5):          # 3 overflows on a 2-slot queue
            bus.publish("logs", {"i": i})
        drained = []
        while not queue.empty():
            drained.append(queue.get_nowait())
        self.assertEqual(drained, [{"i": 3}, {"i": 4}])
        self.assertEqual(REGISTRY.counter("bus_overflow_total"),
                         before + 3)


if __name__ == "__main__":
    unittest.main()
