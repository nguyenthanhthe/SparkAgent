"""Sanity checks for the shipped service definitions."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SystemdUnitTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "ops" / "sparkagent.service").read_text(
            encoding="utf-8")

    def test_required_directives(self):
        for directive in ("[Service]", "ExecStart=", "Restart=always",
                          "User=sparkagent", "NoNewPrivileges=true",
                          "ProtectSystem=strict",
                          "ReadWritePaths=", "EnvironmentFile="):
            self.assertIn(directive, self.text, directive)

    def test_no_secrets_embedded(self):
        import re
        suspicious = re.findall(
            r"(?i)(api[_-]?key|token|password|secret)\s*=\s*\S+",
            self.text)
        self.assertEqual(suspicious, [])

    def test_writable_paths_confined(self):
        line = next(l for l in self.text.splitlines()
                    if l.startswith("ReadWritePaths="))
        paths = line.split("=", 1)[1].split()
        for path in paths:
            self.assertTrue(path.startswith("/opt/sparkagent/"), path)

    def test_hardening_block_present(self):
        hardening = sum(1 for l in self.text.splitlines()
                        if l.split("=")[0] in ("NoNewPrivileges", "PrivateTmp",
                                               "ProtectSystem", "ProtectHome"))
        self.assertGreaterEqual(hardening, 4)


if __name__ == "__main__":
    unittest.main()
