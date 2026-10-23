import unittest

from benchmarks.bench import make_documents, run, timeit


class BenchmarkTests(unittest.TestCase):
    def test_quick_run_produces_results(self):
        results = run(quick=True)
        self.assertGreaterEqual(len(results), 6)
        for result in results:
            self.assertGreater(result.iterations, 0)
            self.assertGreater(result.seconds, 0)
            self.assertGreater(result.ops_per_second, 0)

    def test_result_line_format(self):
        result = timeit("unit-op", lambda: None, 10)
        line = result.line()
        self.assertIn("unit-op", line)
        self.assertIn("ops/s", line)

    def test_make_documents_deterministic(self):
        first = make_documents(10)
        second = make_documents(10)
        self.assertEqual(first, second)
        self.assertEqual(len({doc_id for doc_id, _ in first}), 10)


if __name__ == "__main__":
    unittest.main()
