import unittest

from kernel.errors import (ApprovalRequired, BrainOverloadedError,
                           RateLimitedError, SandboxViolation,
                           SparkError, ToolFailure)


class ErrorHierarchyTests(unittest.TestCase):
    def test_all_derive_from_spark_error(self):
        for exc in (ToolFailure("x"), SandboxViolation("y"),
                    BrainOverloadedError("z"), RateLimitedError("r", 1.5),
                    ApprovalRequired("a", "id-1")):
            self.assertIsInstance(exc, SparkError)

    def test_code_is_class_name(self):
        self.assertEqual(ToolFailure("x").code, "ToolFailure")

    def test_retryable_flags(self):
        self.assertFalse(SparkError("x").retryable)
        self.assertFalse(ToolFailure("x").retryable)
        self.assertTrue(BrainOverloadedError("x").retryable)
        self.assertTrue(RateLimitedError("x").retryable)

    def test_retryable_override(self):
        err = SparkError("flaky", retryable=True)
        self.assertTrue(err.retryable)

    def test_rate_limit_carries_delay(self):
        self.assertEqual(RateLimitedError("slow down", 2.0).retry_after, 2.0)

    def test_approval_carries_id(self):
        self.assertEqual(ApprovalRequired("needs human", "ap-7").approval_id,
                         "ap-7")

    def test_catch_as_parent(self):
        with self.assertRaises(SparkError):
            raise SandboxViolation("escape attempt")


if __name__ == "__main__":
    unittest.main()
