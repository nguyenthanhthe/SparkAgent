import os
import tempfile
import time
import unittest
from pathlib import Path

from openshell.env_guard import (extend_passthrough, is_secret_name,
                                 mask_credential_values, passthrough_names,
                                 sanitize_env)
from openshell.policy import SecurityError
from openshell.profiles import (VALID_PROFILES, UnknownProfile,
                                build_policy, describe_profiles)
from openshell.process_registry import ProcessRegistry


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp())
        self.project = Path(tempfile.mkdtemp())

    def test_all_profiles_build_policies(self):
        for profile in VALID_PROFILES:
            policy = build_policy(profile, self.sandbox, self.project)
            self.assertIsInstance(policy.allowed_programs, set)

    def test_unknown_profile_rejected(self):
        with self.assertRaises(UnknownProfile):
            build_policy("yolo", self.sandbox, self.project)

    def test_strict_blocks_git(self):
        policy = build_policy("strict", self.sandbox, self.project)
        with self.assertRaises(SecurityError):
            policy.validate_command("git", ["status"])

    def test_standard_allows_git(self):
        policy = build_policy("standard", self.sandbox, self.project)
        policy.validate_command("git", ["status"])

    def test_strict_confines_to_sandbox_only(self):
        # project root is NOT an allowed root under strict
        policy = build_policy("strict", self.sandbox, self.project)
        with self.assertRaises(SecurityError):
            policy.validate_command("python", [str(self.project / "x.py")])

    def test_standard_permits_project_root(self):
        policy = build_policy("standard", self.sandbox, self.project)
        policy.validate_command("python", [str(self.project / "x.py")])

    def test_overrides_apply(self):
        policy = build_policy("standard", self.sandbox, self.project,
                              allowed_programs=["python"])
        with self.assertRaises(SecurityError):
            policy.validate_command("git", ["status"])

    def test_describe_profiles_shape(self):
        descriptions = describe_profiles()
        self.assertEqual({d["name"] for d in descriptions},
                         set(VALID_PROFILES))
        strict = next(d for d in descriptions if d["name"] == "strict")
        self.assertFalse(strict["project_root_accessible"])


class ProcessRegistryTests(unittest.TestCase):
    def test_spawn_and_finish_lifecycle(self):
        registry = ProcessRegistry()
        registry.spawn(101, "python", "-c print(1)")
        self.assertEqual(registry.live_count(), 1)
        finished = registry.finish(101, exit_code=0)
        self.assertEqual(registry.live_count(), 0)
        self.assertEqual(finished.exit_code, 0)
        self.assertGreaterEqual(finished.duration_s, 0.0)

    def test_finish_unknown_pid_is_none(self):
        self.assertIsNone(ProcessRegistry().finish(999, exit_code=1))

    def test_history_bounded(self):
        registry = ProcessRegistry(max_history=10)
        for pid in range(50):
            registry.spawn(pid, "python", "x")
            registry.finish(pid, exit_code=0)
        self.assertEqual(len(registry.history(limit=100)), 10)

    def test_stats_counts_failures(self):
        registry = ProcessRegistry()
        for pid, code in ((1, 0), (2, 1), (3, 2)):
            registry.spawn(pid, "p", "a")
            registry.finish(pid, exit_code=code)
        stats = registry.stats()
        self.assertEqual(stats["completed"], 3)
        self.assertEqual(stats["failed"], 2)

    def test_forget_older_than(self):
        registry = ProcessRegistry()
        registry.spawn(1, "p", "a")
        registry.finish(1, exit_code=0)
        time.sleep(0.01)
        dropped = registry.forget_older_than(0.005)
        self.assertEqual(dropped, 1)
        self.assertEqual(registry.history(), [])


class EnvGuardTests(unittest.TestCase):
    def test_secret_names_detected(self):
        for name in ("GLM_API_KEY", "TELEGRAM_BOT_TOKEN",
                     "SPARKAGENT_VAULT_KEY", "MY_SECRET", "DB_PASSWORD",
                     "AWS_CREDENTIAL"):
            self.assertTrue(is_secret_name(name), name)

    def test_benign_names_pass(self):
        for name in ("PATH", "OLLAMA_HOST", "CUDA_PATH", "HOME", "LANG"):
            self.assertFalse(is_secret_name(name), name)

    def test_sanitize_deny_by_default(self):
        env = {"PATH": "/bin", "OLLAMA_HOST": "x", "MY_API_KEY": "k",
               "CUSTOM_TOOL_VAR": "v", "HOME": "/home/u"}
        clean = sanitize_env(env)
        self.assertEqual(clean, {"PATH": "/bin", "OLLAMA_HOST": "x"})

    def test_secrets_dropped_even_if_passthrough_extended(self):
        extend_passthrough("SAFE_VAR", "MY_TOKEN")
        try:
            env = {"SAFE_VAR": "ok", "MY_TOKEN": "nope"}
            clean = sanitize_env(env)
            self.assertEqual(clean, {"SAFE_VAR": "ok"})
        finally:
            passthrough_names()  # leave extended state; harmless for tests

    def test_passthrough_extension_idempotent(self):
        before = len(passthrough_names())
        extend_passthrough("SAFE_VAR")
        extend_passthrough("SAFE_VAR")
        self.assertEqual(len(passthrough_names()), before + 1)

    def test_real_environment_sanitizes(self):
        os.environ["UNITTEST_LEAK_KEY"] = "supersecret"
        try:
            clean = sanitize_env()
            self.assertNotIn("UNITTEST_LEAK_KEY", clean)
            self.assertIn("PATH", clean)
        finally:
            del os.environ["UNITTEST_LEAK_KEY"]

    def test_mask_credential_values(self):
        text = "use sk-ABCDEF1234567890 and ghp_ABCDEF1234567890 tokens"
        masked = mask_credential_values(text)
        self.assertNotIn("sk-ABCDEF", masked)
        self.assertNotIn("ghp_ABCDEF", masked)
        self.assertEqual(masked.count("***"), 2)


if __name__ == "__main__":
    unittest.main()
