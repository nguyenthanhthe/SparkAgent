"""OpenShell security policy: what the agent is allowed to execute.

Three independent layers, all of which must pass before a process spawns:

1. **Program allowlist** — only bare names configured in
   ``openshell.allowed_programs`` (e.g. ``python``, ``git``, ``nvidia-smi``).
   No path separators, no ``cmd``/``powershell`` unless explicitly listed.
2. **Dangerous-pattern denylist** — defense in depth against destructive or
   obfuscated command fragments (format/rd/del of system paths, shutdown,
   registry edits, fork bombs, `curl | sh`, encoded PowerShell, …). Applied
   to the full command line regardless of layer 1.
3. **Path confinement** — any argument that looks like a filesystem path must
   resolve (after ``..`` normalization) inside one of the allowed roots
   (sandbox + project root by default). UNC paths are rejected outright.

Because processes are spawned with ``create_subprocess_exec`` (never through
a shell), metacharacters in arguments cannot be interpreted — the denylist
still scans for them as a second line of defense for shell-enabled installs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Patterns matched against the lowercase full command line. Kept deliberately
# broad: this is defense in depth behind the allowlist, tuned to avoid
# false positives on ordinary development commands (git add, pip install, …).
DANGEROUS_PATTERNS: tuple[re.Pattern, ...] = tuple(re.compile(p, re.IGNORECASE) for p in (
    # destructive filesystem operations
    r"\bformat\s+[a-z]:",
    r"\brd\s+/s",
    r"\bdel\s+/[fqs]",
    r"\berase\s+/[fqs]",
    r"\brmdir\s+/s",
    r"\brm\s+-rf?\s+/(?:etc|var|usr|boot|root|home|bin|sbin)\b",
    r"\bmkfs(\.\w+)?\b",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",
    # system control
    r"\bshutdown\b",
    r"\blogoff\b",
    r"\bbcdedit\b",
    r"\bvssadmin\b",
    r"\bwbadmin\b",
    r"\bregedit\b",
    r"\breg\s+(add|delete|import|restore|load)\b",
    r"\bschtasks\b",
    r"\bnet\s+(user|localgroup|stop|start)\b",
    r"\bnetsh\b",
    r"\bsc\s+(config|stop|delete|failure)\b",
    # fork bomb
    r":\(\)\s*\{.*\};\s*:",
    # obfuscated download/execute chains
    r"powershell.{0,40}-(e|enc|encodedcommand)\b",
    r"\binvoke-expression\b",
    r"\biex\s",
    r"downloadstring",
    r"certutil\s+.{0,30}-?urlcache",
    r"\bbitsadmin\b",
    r"curl\s+[^|]{0,300}\|\s*(ba|z)?sh\b",
    r"wget\s+[^|]{0,300}\|\s*(ba|z)?sh\b",
    # defenses tampering
    r"set-mppreference",
    r"add-mppreference",
    r"stop-process\s+-name\s+(windefend|msmpeng)",
))

_WIN_METACHARS = re.compile(r"[&|^]|[\r\n]")

_DRIVE_ABSOLUTE = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
_DRIVE_BARE = re.compile(r"^[a-z]:$", re.IGNORECASE)


class SecurityError(Exception):
    """A command or path violates the OpenShell policy."""


class SecurityPolicy:
    """Validates commands and paths against the sandbox policy."""

    def __init__(self, allowed_programs: list[str], allowed_roots: list[Path],
                 sandbox_root: Path, allow_shell: bool = False):
        self.allowed_programs = {self._normalize_program(p) for p in allowed_programs}
        self.sandbox_root = sandbox_root.resolve()
        self.allow_shell = allow_shell
        # Precompute comparable (normcase, resolved) roots once.
        self._roots = [os.path.normcase(str(root.resolve())) for root in allowed_roots]

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _normalize_program(name: str) -> str:
        name = name.strip().strip('"').lower()
        for suffix in (".exe", ".cmd", ".bat", ".com"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name

    def _inside_roots(self, path: Path) -> bool:
        try:
            resolved = os.path.normcase(str(path.resolve()))
        except (OSError, RuntimeError):
            return False
        return any(resolved == root or resolved.startswith(root + os.sep)
                   for root in self._roots)

    # --------------------------------------------------------------- commands
    def validate_command(self, program: str, args: list[str] | None = None) -> None:
        """Raise ``SecurityError`` if the command violates policy."""
        args = args or []
        program = program.strip().strip('"')

        if not program:
            raise SecurityError("empty program name")
        if "/" in program or "\\" in program:
            raise SecurityError(
                f"program must be a bare allowlisted name, got path-like {program!r}")
        if self._normalize_program(program) not in self.allowed_programs:
            raise SecurityError(
                f"program {program!r} is not in the allowlist "
                f"({sorted(self.allowed_programs)})")

        joined = " ".join([program, *args])
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(joined):
                raise SecurityError(f"command matches denylist pattern {pattern.pattern!r}")

        if self.allow_shell:
            # Only meaningful when a shell would interpret metacharacters;
            # with create_subprocess_exec they are passed through literally.
            for arg in args:
                if _WIN_METACHARS.search(arg):
                    raise SecurityError(
                        "shell metacharacters in arguments are not allowed "
                        "while allow_shell is enabled")

        for arg in args:
            self._check_arg_path(arg)

    def _check_arg_path(self, arg: str) -> None:
        """Confine path-like arguments to the allowed roots."""
        stripped = arg.strip('"')
        if not stripped or stripped.startswith("-") and len(stripped) <= 2:
            return

        looks_like_path = (
            "/" in stripped or "\\" in stripped
            or _DRIVE_ABSOLUTE.match(stripped) or _DRIVE_BARE.match(stripped)
        )
        if not looks_like_path:
            return

        if stripped.startswith("\\\\"):
            raise SecurityError(f"UNC paths are not allowed: {arg!r}")

        if _DRIVE_ABSOLUTE.match(stripped):
            candidate = Path(stripped)
        else:
            candidate = self.sandbox_root / stripped

        # Split "value" off flag-ish args like `-o=C:\x` or `--file=path`.
        if not candidate.exists() and ("=" in stripped and not stripped.startswith("-")):
            head, _, tail = stripped.partition("=")
            if _DRIVE_ABSOLUTE.match(tail):
                candidate = Path(tail)

        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise SecurityError(f"unresolvable path argument {arg!r}") from exc

        if not self._inside_roots(resolved):
            raise SecurityError(
                f"path argument {arg!r} escapes the allowed roots "
                f"{self._roots}")

    # ------------------------------------------------------------------ paths
    def validate_path(self, path: str | Path, *, write: bool = False) -> Path:
        """Validate a filesystem path used by agent code.

        Reads may touch any allowed root; writes are confined to the sandbox.
        Returns the resolved path.
        """
        raw = Path(str(path).strip('"'))
        if str(raw).startswith("\\\\"):
            raise SecurityError(f"UNC paths are not allowed: {raw}")
        candidate = raw if raw.is_absolute() else (self.sandbox_root / raw)
        resolved = candidate.resolve()
        if not self._inside_roots(resolved):
            raise SecurityError(f"path escapes the allowed roots: {path!r}")
        sandbox = os.path.normcase(str(self.sandbox_root))
        if write and not os.path.normcase(str(resolved)).startswith(sandbox + os.sep):
            raise SecurityError(f"writes are confined to the sandbox: {path!r}")
        return resolved
