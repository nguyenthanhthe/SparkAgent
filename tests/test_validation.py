import unittest

from kernel.errors import SparkError
from kernel.validation import (ValidationError, clamp, require_dict,
                               require_enum, require_http_url,
                               require_identifier, require_int, require_keys,
                               require_number, require_str,
                               sanitize_multiline, validate_tool_args)


class ScalarValidatorTests(unittest.TestCase):
    def test_require_str(self):
        self.assertEqual(require_str("hi", "name"), "hi")
        with self.assertRaises(ValidationError):
            require_str(123, "name")
        with self.assertRaises(ValidationError):
            require_str("", "name")
        with self.assertRaises(ValidationError):
            require_str("x" * 9, "name", max_len=8)

    def test_require_int_bounds_and_coercion(self):
        self.assertEqual(require_int(5, "n"), 5)
        self.assertEqual(require_int("42", "n"), 42)
        self.assertEqual(require_int(-1, "n", minimum=-5), -1)
        with self.assertRaises(ValidationError):
            require_int(True, "n")          # bool is not an int here
        with self.assertRaises(ValidationError):
            require_int(1.5, "n")
        with self.assertRaises(ValidationError):
            require_int(11, "n", maximum=10)
        with self.assertRaises(ValidationError):
            require_int("abc", "n")

    def test_require_number(self):
        self.assertEqual(require_number(2.5, "x"), 2.5)
        self.assertEqual(require_number(3, "x"), 3.0)
        with self.assertRaises(ValidationError):
            require_number("3", "x")
        with self.assertRaises(ValidationError):
            require_number(5, "x", maximum=4)

    def test_require_enum_and_dict_and_keys(self):
        self.assertEqual(require_enum("a", "choice", ["a", "b"]), "a")
        with self.assertRaises(ValidationError):
            require_enum("c", "choice", ["a", "b"])
        self.assertEqual(require_dict({"k": 1}, "obj"), {"k": 1})
        with self.assertRaises(ValidationError):
            require_dict([1], "obj")
        self.assertEqual(require_keys({"a": 1, "b": 2}, ["a"]), {"a": 1, "b": 2})
        with self.assertRaises(ValidationError):
            require_keys({"a": 1}, ["a", "b"])

    def test_require_identifier(self):
        self.assertEqual(require_identifier("web_fetch", "tool"), "web_fetch")
        for bad in ("", "1abc", "has space", "x" * 100, "no/slash"):
            with self.assertRaises(ValidationError):
                require_identifier(bad, "tool")

    def test_require_http_url(self):
        ok = ("http://example.com", "https://example.com/x?y=1",
              "https://8.8.8.8:8080/path")
        for url in ok:
            self.assertEqual(require_http_url(url, "url"), url)
        for bad in ("ftp://x", "example.com", "http://", "//x", 42):
            with self.assertRaises(ValidationError):
                require_http_url(bad, "url")

    def test_validation_error_is_spark_error(self):
        self.assertIsInstance(ValidationError("x"), SparkError)
        self.assertFalse(ValidationError("x").retryable)

    def test_clamp(self):
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(99, 0, 10), 10)

    def test_sanitize_multiline(self):
        dirty = "line1\x00\x1b\nline2\ttab\x07"
        cleaned = sanitize_multiline(dirty)
        for control in ("\x00", "\x1b", "\x07"):
            self.assertNotIn(control, cleaned)
        self.assertIn("line1\nline2\ttab", cleaned)
        many = "\n".join(f"l{i}" for i in range(500))
        self.assertIn("[truncated]", sanitize_multiline(many, max_lines=100))


class ToolArgsValidatorTests(unittest.TestCase):
    SPEC = {
        "text": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False},
        "mode": {"type": "string", "enum": ["fast", "slow"]},
    }

    def test_valid_args_pass(self):
        args = validate_tool_args(self.SPEC,
                                  {"text": "hi", "limit": "3",
                                   "mode": "fast"})
        self.assertEqual(args["limit"], 3)
        self.assertEqual(args["mode"], "fast")

    def test_missing_required_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_tool_args(self.SPEC, {"limit": 1})
        self.assertIn("text", str(ctx.exception))

    def test_unknown_parameter_rejected(self):
        with self.assertRaises(ValidationError):
            validate_tool_args(self.SPEC, {"text": "hi", "extra": 1})

    def test_enum_enforced(self):
        with self.assertRaises(ValidationError):
            validate_tool_args(self.SPEC, {"text": "hi", "mode": "turbo"})

    def test_optional_missing_ok(self):
        args = validate_tool_args(self.SPEC, {"text": "hi"})
        self.assertNotIn("limit", args)


if __name__ == "__main__":
    unittest.main()
