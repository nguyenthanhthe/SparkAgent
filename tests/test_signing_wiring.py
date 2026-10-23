import os
import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon
from security.signatures import derive_signing_key


class SigningWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_key_derived_when_vault_unlocked(self):
        old = os.environ.get("SPARKAGENT_VAULT_KEY")
        os.environ["SPARKAGENT_VAULT_KEY"] = "wiring-test-master"
        try:
            daemon = AgentDaemon(Config.load())
            expected = derive_signing_key("wiring-test-master",
                                          domain="skill")
            self.assertEqual(daemon.forge.signing_key, expected)
        finally:
            if old is None:
                os.environ.pop("SPARKAGENT_VAULT_KEY", None)
            else:
                os.environ["SPARKAGENT_VAULT_KEY"] = old

    async def test_no_key_when_vault_locked(self):
        old = os.environ.get("SPARKAGENT_VAULT_KEY")
        os.environ.pop("SPARKAGENT_VAULT_KEY", None)
        try:
            daemon = AgentDaemon(Config.load())
            self.assertIsNone(daemon.forge.signing_key)
        finally:
            if old is not None:
                os.environ["SPARKAGENT_VAULT_KEY"] = old

    async def test_config_opt_out(self):
        old = os.environ.get("SPARKAGENT_VAULT_KEY")
        os.environ["SPARKAGENT_VAULT_KEY"] = "wiring-test-master"
        try:
            daemon = AgentDaemon(Config({"tools": {"skillforge":
                                                   {"sign_skills": False}}}))
            self.assertIsNone(daemon.forge.signing_key)
        finally:
            if old is None:
                os.environ.pop("SPARKAGENT_VAULT_KEY", None)
            else:
                os.environ["SPARKAGENT_VAULT_KEY"] = old


if __name__ == "__main__":
    unittest.main()
