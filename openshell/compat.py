"""Detection and capability probing for the real NVIDIA OpenShell runtime.

NVIDIA OpenShell (https://github.com/NVIDIA/OpenShell) is a sandboxed
runtime for autonomous agents: kernel-confined sandboxes, policy-governed
filesystem/syscall/network access, and credential injection at approved
endpoints. When it is installed, SparkAgent can route execution through
real sandboxes instead of relying solely on this package's policy-level
guardrails.

This module only *observes*: version probe, CLI presence, optional
gateway ping. Nothing here executes agent payloads.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from typing import Any

from kernel.logging import get_logger

logger = get_logger("openshell.compat")

CLI_NAME = "openshell"
VERSION_TIMEOUT_S = 10.0
# keep the probe modest: we only ever run `--version`, a fixed literal
_VERSION_ARGV = (CLI_NAME, "--version")


@dataclass
class OpenShellInfo:
    available: bool = False
    version: str = ""
    cli_path: str | None = None
    detail: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"available": self.available, "version": self.version,
                "cli_path": self.cli_path, "detail": self.detail}


_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def parse_version(output: str) -> str:
    """Extract a semver-ish version from CLI output ('openshell 0.4.2')."""
    match = _VERSION_RE.search(output or "")
    return match.group(1) if match else ""


def cli_present() -> str | None:
    """Path to the openshell binary, or None. Pure lookup, no execution."""
    return shutil.which(CLI_NAME)


async def probe_version(runner=None) -> OpenShellInfo:
    """Run ``openshell --version`` and parse it.

    ``runner`` is injectable for tests: async fn(argv: tuple) ->
    (returncode, stdout). Production uses asyncio subprocess directly —
    the argv is the fixed literal above, never agent-controlled input.
    """
    info = OpenShellInfo()
    info.cli_path = cli_present()
    if info.cli_path is None:
        info.detail = "openshell CLI not found on PATH"
        return info

    if runner is None:
        async def _real(argv: tuple) -> tuple[int, str]:
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT)
                stdout, _ = await asyncio.wait_for(process.communicate(),
                                                   VERSION_TIMEOUT_S)
                return process.returncode or 0, \
                    stdout.decode("utf-8", errors="replace")
            except (OSError, asyncio.TimeoutError) as exc:
                return -1, str(exc)
        runner = _real

    code, output = await runner(_VERSION_ARGV)
    info.raw = {"returncode": code, "output": output[:400]}
    if code != 0:
        info.detail = f"openshell --version exited {code}"
        return info
    info.version = parse_version(output)
    info.available = True
    info.detail = "ok"
    logger.info("NVIDIA OpenShell detected: v%s at %s", info.version,
                info.cli_path)
    return info


def minimum_version_met(version: str, minimum: str = "0.1.0") -> bool:
    """Loose version gate: compares numeric segments."""
    def segments(text: str) -> list[int]:
        return [int(part) for part in (text or "0.0.0").split(".")[:3]]

    have, want = segments(version), segments(minimum)
    for index in range(max(len(have), len(want))):
        left = have[index] if index < len(have) else 0
        right = want[index] if index < len(want) else 0
        if left != right:
            return left > right
    return True
