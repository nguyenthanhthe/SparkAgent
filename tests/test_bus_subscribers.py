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


if __name__ == "__main__":
    unittest.main()
