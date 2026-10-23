import os
import tempfile
import unittest
from pathlib import Path

from openshell.vault import SecretVault, VaultLocked, _decrypt, _encrypt


class CryptoEnvelopeTests(unittest.TestCase):
    def test_roundtrip(self):
        key = b"k" * 32
        blob = _encrypt(key, b"hello world")
        self.assertEqual(_decrypt(key, blob[:16], blob[16:32], blob[32:48], blob[48:]),
                         b"hello world")

    def test_tamper_detected(self):
        key = b"k" * 32
        blob = bytearray(_encrypt(key, b"secret data"))
        blob[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            _decrypt(key, bytes(blob[:16]), bytes(blob[16:32]),
                     bytes(blob[32:48]), bytes(blob[48:]))

    def test_wrong_key_detected(self):
        blob = _encrypt(b"a" * 32, b"secret data")
        with self.assertRaises(ValueError):
            _decrypt(b"b" * 32, blob[:16], blob[16:32], blob[32:48], blob[48:])


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = self.tmp / "vault.bin"
        self.key = "unit-test-master-key"
        self._old = os.environ.get("SPARKAGENT_VAULT_KEY")
        os.environ["SPARKAGENT_VAULT_KEY"] = self.key

    def tearDown(self):
        if self._old is None:
            os.environ.pop("SPARKAGENT_VAULT_KEY", None)
        else:
            os.environ["SPARKAGENT_VAULT_KEY"] = self._old

    def test_store_roundtrip(self):
        vault = SecretVault(self.store)
        vault.set("UNIT_SECRET", "s3cret-value-xyz")
        reloaded = SecretVault(self.store)
        self.assertEqual(reloaded.get("UNIT_SECRET"), "s3cret-value-xyz")

    def test_store_file_not_plaintext(self):
        vault = SecretVault(self.store)
        vault.set("UNIT_SECRET", "plaintext-canary")
        blob = self.store.read_bytes()
        self.assertNotIn(b"plaintext-canary", blob)

    def test_env_takes_priority(self):
        old = os.environ.get("UNIT_ENV_SECRET")
        os.environ["UNIT_ENV_SECRET"] = "from-env"
        try:
            vault = SecretVault(self.store)
            vault.set("UNIT_ENV_SECRET", "from-store")
            self.assertEqual(vault.get("UNIT_ENV_SECRET"), "from-env")
        finally:
            if old is None:
                os.environ.pop("UNIT_ENV_SECRET", None)
            else:
                os.environ["UNIT_ENV_SECRET"] = old

    def test_require_missing_raises(self):
        vault = SecretVault(self.store)
        with self.assertRaises(VaultLocked):
            vault.require("NO_SUCH_SECRET_42")

    def test_redact_known_value_and_patterns(self):
        vault = SecretVault(self.store)
        vault._secrets["TOKEN_X"] = "abc123def456"
        text = vault.redact(
            "token=abc123def456 and sk-ABCDEFGHIJKLMNOP123456 and password: hunter2secret")
        self.assertNotIn("abc123def456", text)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP123456", text)
        self.assertIn("***REDACTED***", text)


if __name__ == "__main__":
    unittest.main()
