"""Safe subprocess executor (Windows-first).

Every execution goes through :class:`SecurityPolicy` first, then spawns via
``create_subprocess_exec`` (no shell). Output is size-capped and redacted,
timeouts kill the whole process tree (``taskkill /T /F`` on Windows), and an
audit event is published for every attempt.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from kernel.bus import EventBus
from kernel.limits import RateLimiterSet
from kernel.logging import get_logger
from kernel.metrics import REGISTRY
from openshell.env_guard import sanitize_env
from openshell.policy import SecurityError, SecurityPolicy
from openshell.process_registry import ProcessRegistry
from openshell.vault import SecretVault

logger = get_logger("executor")


@dataclass
class ExecResult:
    program: str
    args: tuple[str, ...] = ()
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    timed_out: bool = False
    blocked_reason: str | None = None
    ok: bool = field(init=False)

    def __post_init__(self) -> None:
        self.ok = (not self.timed_out and not self.blocked_reason
                   and self.exit_code == 0)

    def summary(self, limit: int = 400) -> str:
        if self.blocked_reason:
            return f"BLOCKED by policy: {self.blocked_reason}"
        parts = [f"exit={self.exit_code}", f"{self.duration:.1f}s"]
        if self.timed_out:
            parts.append("timed out")
        if self.stdout:
            parts.append(f"stdout: {_clip(self.stdout, limit)}")
        if self.stderr:
            parts.append(f"stderr: {_clip(self.stderr, limit)}")
        return " | ".join(parts)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 15] + "…[truncated]"


def _metric_safe(program: str) -> str:
    """Program name -> metric-name-safe slug (exec_seconds_<slug>)."""
    slug = "".join(c if c.isalnum() else "_" for c in program.lower())
    return slug.strip("_") or "unknown"


class SafeExecutor:
    def __init__(self, policy: SecurityPolicy, vault: SecretVault,
                 bus: EventBus, timeout: float = 60.0,
                 max_output_bytes: int = 131072,
                 registry: ProcessRegistry | None = None,
                 sanitize_child_env: bool = True,
                 execs_per_minute: float = 0.0,
                 program_timeouts: dict[str, float] | None = None):
        self.policy = policy
        self.vault = vault
        self.bus = bus
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.registry = registry or ProcessRegistry()
        self.sanitize_child_env = sanitize_child_env
        # 0 disables limiting; capacity 1 token with continuous refill
        # means at most execs_per_minute spawns per program per minute.
        self._limiters = RateLimiterSet(
            capacity=max(1.0, execs_per_minute),
            refill_per_second=execs_per_minute / 60.0) \
            if execs_per_minute > 0 else None
        # per-program wall-clock budget (seconds): a run requesting more
        # than its program's budget is blocked at the admission gate
        self.program_timeouts = {
            str(name).lower(): float(budget)
            for name, budget in (program_timeouts or {}).items()}
        self.policy.sandbox_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ public
    async def run(self, program: str, args: list[str] | None = None,
                  timeout: float | None = None,
                  cwd: Path | None = None) -> ExecResult:
        """Validate and run a command inside the sandbox."""
        args = [str(a) for a in (args or [])]
        timeout = timeout or self.timeout

        workdir = Path(cwd) if cwd is not None else self.policy.sandbox_root
        admitted = self._admit(program, args, workdir=workdir, timeout=timeout)
        if admitted[0] is None:
            return admitted[1]
        exe = admitted[0]
        return await self._spawn_and_collect(
            [exe, *args], program, args, timeout, workdir)

    def _admit(self, program: str, args: list[str],
               workdir: Path, timeout: float) \
            -> tuple[str | None, "ExecResult | None"]:
        """Policy + workdir + budget + rate-limit + PATH admission.
        Returns (exe, None) to proceed or (None, blocked_result) to stop."""
        try:
            self.policy.validate_command(program, args)
            self.policy.validate_workdir(program, workdir)
        except SecurityError as exc:
            logger.warning("blocked command %s %s: %s", program, args, exc)
            self.bus.publish("audit", {"actor": "executor", "action": "exec.blocked",
                                       "detail": f"{program} {args!r}: {exc}"})
            return None, ExecResult(program=program, args=tuple(args),
                                    exit_code=None, blocked_reason=str(exc))
        budget = self.program_timeouts.get(program.lower())
        if budget is not None and timeout > budget + 1e-9:
            REGISTRY.incr("exec_timebudget_blocked_total")
            reason = (f"time budget: {program!r} allows {budget:g}s, "
                      f"run requested {timeout:g}s")
            logger.warning("blocked command %s %s: %s", program, args, reason)
            self.bus.publish("audit", {"actor": "executor",
                                       "action": "exec.blocked",
                                       "detail": f"{program} {args!r}: "
                                                 f"{reason}"})
            return None, ExecResult(program=program, args=tuple(args),
                                    exit_code=None, blocked_reason=reason)

        if self._limiters is not None and \
                not self._limiters.try_take(program.lower()):
            reason = (f"rate limit: {program!r} exceeded its per-minute "
                      "execution budget")
            logger.warning(reason)
            self.bus.publish("audit", {"actor": "executor",
                                       "action": "exec.ratelimited",
                                       "detail": program})
            return None, ExecResult(program=program, args=tuple(args),
                                    exit_code=None, blocked_reason=reason)

        exe = shutil.which(program)
        if exe is None:
            return None, ExecResult(program=program, args=tuple(args),
                                    exit_code=None,
                                    blocked_reason=f"program not found on "
                                    f"PATH: {program}")
        return exe, None

    async def _spawn_and_collect(self, argv: list[str], program: str,
                                 args: list[str], timeout: float,
                                 cwd: Path | None) -> ExecResult:
        """Spawn the (already admitted) argv, cap output, redact, audit."""
        base_args = self.vault.redact(" ".join(args))
        workdir = cwd or self.policy.sandbox_root
        started = time.monotonic()
        self.bus.publish("audit", {"actor": "executor", "action": "exec.start",
                                   "detail": f"{program} {base_args}"})
        child_env = sanitize_env() if self.sanitize_child_env else None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, cwd=str(workdir), env=child_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            return ExecResult(program=program, args=tuple(args), exit_code=None,
                              blocked_reason=f"spawn failed: {exc}")
        self.registry.spawn(process.pid, program, base_args)

        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await self._kill_tree(process)
            stdout_b, stderr_b = await process.communicate()

        duration = time.monotonic() - started
        REGISTRY.observe(f"exec_seconds_{_metric_safe(program)}", duration)
        stdout = self.vault.redact(_decode(stdout_b, self.max_output_bytes))
        stderr = self.vault.redact(_decode(stderr_b, self.max_output_bytes))
        self.registry.finish(process.pid, process.returncode,
                             timed_out=timed_out)
        result = ExecResult(program=program, args=tuple(args),
                            exit_code=process.returncode, stdout=stdout,
                            stderr=stderr, duration=duration, timed_out=timed_out)
        self.bus.publish("audit", {
            "actor": "executor",
            "action": "exec.finish",
            "detail": (f"{program} exit={result.exit_code} {duration:.1f}s"
                       + (" TIMEOUT" if timed_out else ""))})
        logger.info("exec %s -> exit=%s %.1fs", base_args, result.exit_code, duration)
        return result

    async def check(self, program: str) -> bool:
        """True if the program is allowlisted and present on PATH."""
        try:
            self.policy.validate_command(program, [])
        except SecurityError:
            return False
        return shutil.which(program) is not None

    async def dry_run(self, program: str, args: list[str] | None = None) \
            -> dict:
        """Report what WOULD happen without spawning: policy verdict,
        denylist/allowlist reasons, resolved executable, rate budget."""
        args = [str(a) for a in (args or [])]
        try:
            self.policy.validate_command(program, args)
            decision = "allowed"
            reason = ""
        except SecurityError as exc:
            decision, reason = "blocked", str(exc)
        resolved = shutil.which(program) if decision == "allowed" else None
        rate_ok = True
        rate_note = "unlimited"
        if decision == "allowed" and self._limiters is not None:
            rate_ok = self._limiters.bucket(program.lower()).peek() >= 1.0
            rate_note = ("ok" if rate_ok else
                         "would be rate-limited this minute")
        return {"program": program, "args": args, "decision": decision,
                "reason": reason, "executable": resolved,
                "rate_limit": rate_note}

    # ----------------------------------------------------------------- helpers
    async def _kill_tree(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if sys.platform == "win32":
            try:
                await asyncio.create_subprocess_exec(
                    "taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
            except OSError:
                process.kill()
        else:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except OSError:
                process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


def _decode(data: bytes, cap: int) -> str:
    if not data:
        return ""
    if len(data) > cap:
        half = cap // 2
        data = data[:half] + b"\n...[output truncated]...\n" + data[-half:]
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
