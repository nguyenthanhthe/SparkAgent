"""OpenShellExecutor — route admitted commands through a real
NVIDIA OpenShell sandbox when the runtime is present.

Layering: SparkAgent's policy layer (allowlist, denylist, path
confinement, rate limits) stays as the FIRST gate — defense in depth —
and execution then happens inside a kernel-confined OpenShell sandbox
(``openshell sandbox exec --sandbox <name> -- <exe> <args...>``) instead
of a bare host process. When OpenShell is absent or below the minimum
version, execution transparently falls back to the host policy executor,
so the same code path works everywhere.

Output handling, redaction, audit events, kill-trees, and the process
registry are inherited from :class:`openshell.executor.SafeExecutor`.
"""

from __future__ import annotations

from pathlib import Path

from kernel.logging import get_logger
from openshell import compat
from openshell.executor import SafeExecutor

logger = get_logger("openshell.backend")

DEFAULT_SANDBOX_NAME = "sparkagent"
MINIMUM_VERSION = "0.1.0"


class OpenShellExecutor(SafeExecutor):
    """SafeExecutor whose admitted spawns run inside an OpenShell sandbox."""

    def __init__(self, *args, sandbox_name: str = DEFAULT_SANDBOX_NAME,
                 minimum_version: str = MINIMUM_VERSION,
                 info: compat.OpenShellInfo | None = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.sandbox_name = sandbox_name
        self.minimum_version = minimum_version
        self._info = info
        self._probe_attempted = info is not None
        self.backend_stats = {"sandboxed": 0, "fallback": 0}

    # ----------------------------------------------------------------- probe
    async def ensure_ready(self) -> bool:
        """Probe once; True when the runtime is present and new enough."""
        if not self._probe_attempted:
            self._info = await compat.probe_version()
            self._probe_attempted = True
        info = self._info
        if info is None or not info.available:
            return False
        if not compat.minimum_version_met(info.version, self.minimum_version):
            logger.warning("OpenShell v%s below minimum v%s — falling back",
                           info.version, self.minimum_version)
            return False
        return True

    @property
    def info(self) -> compat.OpenShellInfo | None:
        return self._info

    def describe_backend(self) -> dict:
        info = self._info
        return {"backend": "openshell" if info and info.available
                else "policy-fallback",
                "sandbox": self.sandbox_name,
                "runtime": info.to_dict() if info else None,
                **self.backend_stats}

    # ------------------------------------------------------------------- run
    async def run(self, program: str, args: list[str] | None = None,
                  timeout: float | None = None,
                  cwd: Path | None = None):
        args = [str(a) for a in (args or [])]
        timeout = timeout or self.timeout
        workdir = Path(cwd) if cwd is not None else self.policy.sandbox_root

        # 1. the policy layer always runs first, regardless of backend
        admitted = self._admit(program, args, workdir=workdir, timeout=timeout)
        if admitted[0] is None:
            return admitted[1]
        exe = admitted[0]

        # 2. sandbox route when the runtime is available
        if await self.ensure_ready():
            argv = ["openshell", "sandbox", "exec",
                    "--sandbox", self.sandbox_name, "--", exe, *args]
            self.backend_stats["sandboxed"] += 1
            self.bus.publish("audit", {
                "actor": "executor", "action": "exec.sandboxed",
                "detail": f"{program} via openshell sandbox "
                          f"{self.sandbox_name!r}"})
            return await self._spawn_and_collect(argv, program, args,
                                                 timeout, workdir)

        # 3. transparent fallback to the host policy executor
        self.backend_stats["fallback"] += 1
        return await self._spawn_and_collect([exe, *args], program, args,
                                             timeout, workdir)
