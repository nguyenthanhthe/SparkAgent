import math
import unittest

from tools.calc import CalcError, evaluate, try_evaluate
from tools.textops import (dedupe_preserve_order, domains_of, extract_dates,
                           extract_emails, extract_numbers, extract_urls,
                           line_summary, slugify, truncate_middle,
                           word_frequencies)


class CalculatorTests(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertAlmostEqual(evaluate("1 + 2 * 3"), 7.0)
        self.assertAlmostEqual(evaluate("(1 + 2) * 3"), 9.0)
        self.assertAlmostEqual(evaluate("10 / 4"), 2.5)
        self.assertAlmostEqual(evaluate("7 // 2"), 3.0)
        self.assertAlmostEqual(evaluate("7 % 3"), 1.0)
        self.assertAlmostEqual(evaluate("2 ** 10"), 1024.0)
        self.assertAlmostEqual(evaluate("-5 + 3"), -2.0)

    def test_constants_and_functions(self):
        self.assertAlmostEqual(evaluate("pi"), math.pi)
        self.assertAlmostEqual(evaluate("sqrt(16)"), 4.0)
        self.assertAlmostEqual(evaluate("max(1, 5, 3)"), 5.0)
        self.assertAlmostEqual(evaluate("abs(-7) + ceil(1.2)"), 9.0)
        self.assertAlmostEqual(evaluate("factorial(5)"), 120.0)

    def test_variables(self):
        self.assertAlmostEqual(evaluate("x * 2", {"x": 21}), 42.0)

    def test_division_by_zero_clear_error(self):
        with self.assertRaises(CalcError) as ctx:
            evaluate("1 / 0")
        self.assertIn("division by zero", str(ctx.exception))

    def test_code_injection_rejected(self):
        for evil in ("__import__('os').system('x')", "[1,2]", "'a' + 'b'",
                     "x.y", "lambda: 1", "a if b else c", "{'k': 1}",
                     "f-string", "\"str\""):
            with self.assertRaises(CalcError, msg=evil):
                evaluate(evil)

    def test_unknown_name_rejected(self):
        with self.assertRaises(CalcError):
            evaluate("unknown_var + 1")

    def test_huge_exponent_rejected(self):
        with self.assertRaises(CalcError):
            evaluate("9 ** 999999")

    def test_deep_nesting_rejected(self):
        # parentheses vanish in the AST; operator chains create real depth
        with self.assertRaises(CalcError):
            evaluate("1+" * 80 + "1")   # depth ~80 > 60

    def test_overflow_rejected(self):
        with self.assertRaises(CalcError):
            evaluate("exp(9999)")

    def test_try_evaluate_shapes(self):
        good = try_evaluate("2 + 2")
        self.assertEqual(good, {"ok": True, "value": 4.0, "rounded": 4.0})
        bad = try_evaluate("1/0")
        self.assertFalse(bad["ok"])
        self.assertIn("error", bad)

    def test_input_length_guard(self):
        with self.assertRaises(CalcError):
            evaluate("1+" * 300 + "1")


class TextOpsTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify("  Über cool  "), "ber-cool")
        self.assertEqual(slugify("---"), "item")
        self.assertLessEqual(len(slugify("x" * 200)), 60)

    def test_word_frequencies_ranks_and_filters(self):
        text = "the cat sat on the mat and the cat ran"
        freqs = word_frequencies(text, top=3)
        self.assertEqual(freqs[0], ("cat", 2))
        words = [w for w, _ in freqs]
        self.assertNotIn("the", words)   # stopword filtered

    def test_extract_urls_and_domains(self):
        text = ("visit https://example.com/a and http://test.org:8080/x, "
                "but not ftp://nope")
        urls = extract_urls(text)
        self.assertEqual(len(urls), 2)
        self.assertIn("example.com", domains_of(urls))

    def test_extract_emails(self):
        found = extract_emails("contact a.b@corp.io or x@y.co.uk plz")
        self.assertEqual(found, ["a.b@corp.io", "x@y.co.uk"])

    def test_extract_numbers(self):
        self.assertEqual(extract_numbers("t:-3 v:2.5 z:10"),
                         [-3.0, 2.5, 10.0])

    def test_extract_dates(self):
        text = "due 2026-10-24 and 2026-12-01T09:30 but not 2026-1-1"
        dates = extract_dates(text)
        self.assertIn("2026-10-24", dates)
        self.assertIn("2026-12-01T09:30", dates)

    def test_truncate_middle(self):
        text = "A" * 100
        short = truncate_middle(text, 21)
        self.assertEqual(len(short), 21)
        self.assertIn("…", short)
        self.assertEqual(truncate_middle("short", 10), "short")

    def test_line_summary(self):
        summary = line_summary("one\ntwo\n\nthree")
        self.assertEqual(summary["lines"], 4)
        self.assertEqual(summary["non_empty_lines"], 3)
        self.assertEqual(summary["words"], 3)

    def test_dedupe_preserve_order(self):
        self.assertEqual(dedupe_preserve_order([1, 2, 1, 3, 2]), [1, 2, 3])
        self.assertEqual(dedupe_preserve_order(["a", "a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
