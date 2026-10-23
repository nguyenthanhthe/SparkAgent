import tempfile
import unittest
from pathlib import Path

from openshell.policy import SecurityError, SecurityPolicy


def make_policy(sandbox: Path, **kw) -> SecurityPolicy:
    defaults = dict(
        allowed_programs=["python", "git", "pip", "nvidia-smi"],
        allowed_roots=[sandbox, Path(__file__).resolve().parents[1]],
        sandbox_root=sandbox,
        allow_shell=False,
    )
    defaults.update(kw)
    return SecurityPolicy(**defaults)


class ProgramAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.policy = make_policy(Path(tempfile.mkdtemp()))

    def test_allowed_bare_program_passes(self):
        self.policy.validate_command("python", ["--version"])

    def test_program_with_path_separator_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("C:/Windows/System32/cmd.exe", [])

    def test_unknown_program_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("cmd", [])

    def test_exe_suffix_normalized(self):
        self.policy.validate_command("python.EXE", [])

    def test_empty_program_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("", [])


class DenylistTests(unittest.TestCase):
    def setUp(self):
        self.policy = make_policy(Path(tempfile.mkdtemp()))

    def assert_blocked(self, program, args):
        with self.assertRaises(SecurityError):
            self.policy.validate_command(program, args)

    def test_shutdown(self):
        self.assert_blocked("git", ["push", "&&", "shutdown", "/s"])  # metachars first

    def test_del_force(self):
        self.assert_blocked("python", ["x", "del", "/f", "/q", "C:/*"])

    def test_fork_bomb_fragment(self):
        self.assert_blocked("python", ["-c", ":(){ :|:& };:"])

    def test_encoded_powershell(self):
        self.assert_blocked("python", ["run", "powershell", "-enc", "AAAA"])

    def test_curl_pipe_sh(self):
        self.assert_blocked("python", ["wrapper", "curl", "http://x/install.sh", "|", "sh"])

    def test_registry_edit(self):
        self.assert_blocked("python", ["-c", "reg add HKLM\\Software\\X"])

    def test_format_drive(self):
        self.assert_blocked("python", ["-c", "format D: /y"])

    def test_benign_git_commands_pass(self):
        self.policy.validate_command("git", ["add", "."])
        self.policy.validate_command("git", ["commit", "-m", "feat: message & stuff"])
        self.policy.validate_command("pip", ["install", "requests>=2.0"])


class PathConfinementTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp())
        (self.sandbox / "nested").mkdir(exist_ok=True)
        self.policy = make_policy(self.sandbox)

    def test_sandbox_relative_path_allowed(self):
        self.policy.validate_command("python", ["scripts/run.py"])

    def test_dotdot_escape_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("python", ["../../windows/system32/evil.py"])

    def test_absolute_outside_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("python", ["C:/Windows/System32/config.sys"])

    def test_unc_rejected(self):
        with self.assertRaises(SecurityError):
            self.policy.validate_command("python", ["\\\\server\\share\\x.py"])

    def test_project_root_allowed(self):
        repo = Path(__file__).resolve().parents[1]
        self.policy.validate_command("git", ["-C", str(repo), "status"])

    def test_nonexistent_relative_still_confined(self):
        # 'sub/x.py' inside sandbox resolves into sandbox even if it doesn't exist
        self.policy.validate_command("python", ["sub/x.py"])

    def test_validate_path_write_confined(self):
        inside = self.policy.validate_path("notes.txt", write=True)
        self.assertTrue(str(inside).startswith(str(self.policy.sandbox_root)))
        with self.assertRaises(SecurityError):
            self.policy.validate_path("../outside.txt", write=True)


class MetacharTests(unittest.TestCase):
    def test_shell_metachars_rejected_when_shell_enabled(self):
        policy = make_policy(Path(tempfile.mkdtemp()), allow_shell=True)
        with self.assertRaises(SecurityError):
            policy.validate_command("git", ["log", "|", "grep", "x"])

    def test_metachars_literal_when_shell_disabled(self):
        # exec mode never interprets metacharacters, so benign text passes
        policy = make_policy(Path(tempfile.mkdtemp()), allow_shell=False)
        policy.validate_command("git", ["log", "--grep=x|y"])


if __name__ == "__main__":
    unittest.main()
