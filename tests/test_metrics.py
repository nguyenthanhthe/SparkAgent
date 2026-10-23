import unittest

from kernel.metrics import MetricsRegistry, REGISTRY


class MetricsTests(unittest.TestCase):
    def test_counter_increments(self):
        reg = MetricsRegistry()
        self.assertEqual(reg.incr("episodes"), 1.0)
        self.assertEqual(reg.incr("episodes"), 2.0)
        self.assertEqual(reg.incr("episodes", 3.0), 5.0)
        self.assertEqual(reg.counter("episodes"), 5.0)
        self.assertEqual(reg.counter("never_touched"), 0.0)

    def test_gauge_sets_and_reads(self):
        reg = MetricsRegistry()
        reg.gauge("vram_free_mb", 2048)
        self.assertEqual(reg.gauge_value("vram_free_mb"), 2048)
        reg.gauge("vram_free_mb", 512)
        self.assertEqual(reg.gauge_value("vram_free_mb"), 512)
        self.assertIsNone(reg.gauge_value("unset"))

    def test_histogram_counts_and_percentiles(self):
        reg = MetricsRegistry()
        for value in (0.1, 0.2, 0.3, 0.4):
            reg.observe("latency", value)
        hist = reg.histogram("latency")
        self.assertEqual(hist["count"], 4)
        self.assertAlmostEqual(hist["sum"], 1.0, places=6)
        self.assertEqual(hist["p50"], 0.3)   # sorted[1] of 4 -> 0.3? see below
        self.assertEqual(hist["p95"], 0.4)

    def test_bucket_cumulative_is_monotonic(self):
        reg = MetricsRegistry()
        for value in (0.001, 0.05, 5.0, 100.0):
            reg.observe("sizes", value)
        hist = reg.histogram("sizes")
        counts = [hist["buckets"]["0.005"], hist["buckets"]["0.05"],
                  hist["buckets"]["5.0"], hist["buckets"]["+Inf"]]
        self.assertEqual(counts, [1, 2, 3, 4])

    def test_timed_records_positive_duration(self):
        reg = MetricsRegistry()
        import time
        with reg.timed("block"):
            time.sleep(0.005)
        hist = reg.histogram("block")
        self.assertGreaterEqual(hist["count"], 1)
        self.assertGreaterEqual(hist["sum"], 0.005)

    def test_render_text_prometheus_format(self):
        reg = MetricsRegistry()
        reg.incr("tasks_done")
        reg.gauge("heap_mb", 10)
        reg.observe("latency", 0.2)
        text = reg.render_text()
        self.assertIn("tasks_done 1.0", text)
        self.assertIn("heap_mb 10.0", text)
        self.assertIn('latency_bucket{le="0.1"} 0', text)
        self.assertIn('latency_bucket{le="0.25"} 1', text)
        self.assertIn('latency_bucket{le="+Inf"} 1', text)
        self.assertIn("latency_count 1", text)

    def test_snapshot_shape(self):
        reg = MetricsRegistry()
        reg.incr("x")
        snap = reg.snapshot()
        self.assertEqual(set(snap), {"counters", "gauges", "histograms"})

    def test_default_registry_exists(self):
        REGISTRY.incr("global_test_counter_xyz")
        self.assertGreaterEqual(REGISTRY.counter("global_test_counter_xyz"), 1)


if __name__ == "__main__":
    unittest.main()
