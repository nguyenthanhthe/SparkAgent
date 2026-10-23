"""OpenShell — SparkAgent's safe process execution layer.

Public surface:
  - ``SecurityPolicy``  command/argument validation (allowlist + denylist +
                        path confinement)
  - ``SecurityError``   raised when a command violates policy
  - ``SecretVault``     encrypted secret storage + log redaction
  - ``SafeExecutor``    asyncio subprocess runner with timeouts and kill trees
"""

from openshell.policy import SecurityError, SecurityPolicy
from openshell.vault import SecretVault

__all__ = ["SecurityError", "SecurityPolicy", "SecretVault", "SafeExecutor"]


def __getattr__(name: str):  # lazy import to keep module import cheap
    if name == "SafeExecutor":
        from openshell.executor import SafeExecutor
        return SafeExecutor
    raise AttributeError(name)
