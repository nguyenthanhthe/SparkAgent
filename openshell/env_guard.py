"""Child-process environment sanitization.

By default child processes inherit our environment — including the vault
master key and every API token SparkAgent holds. ``sanitize_env`` is
deny-by-default: only variables on the explicit passthrough list survive,
and even those are dropped if their name looks credential-shaped
(``*KEY*``, ``*TOKEN*``, ``*SECRET*``, ``*PASSWORD*``).
"""

from __future__ import annotations

import fnmatch
import os
import re

# variable names that must never leak into child processes
_SECRET_NAME_PATTERNS: tuple[str, ...] = (
    "*KEY*", "*TOKEN*", "*SECRET*", "*PASSWORD*", "*CREDENTIAL*",
)

# always-passed-through variables the toolchain and CUDA/Ollama need
_PASSTHROUGH: tuple[str, ...] = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "WINDIR",
    "TEMP", "TMP", "USERNAME", "USERPROFILE", "COMPUTERNAME", "OS",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "HOMEDRIVE", "HOMEPATH",
    "LANG", "LC_ALL", "PYTHONIOENCODING", "PYTHONUTF8",
    "PYTHONDONTWRITEBYTECODE", "CUDA_PATH", "CUDA_HOME", "OLLAMA_HOST",
)

_CREDENTIAL_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|ghp_[A-Za-z0-9]{10,}|xox[bap]-[A-Za-z0-9\-]{8,}|"
    r"AKIA[0-9A-Z]{12,}|Bearer\s+[A-Za-z0-9._\-]{12,})", re.IGNORECASE)


def is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(fnmatch.fnmatchcase(upper, pattern)
               for pattern in _SECRET_NAME_PATTERNS)


def sanitize_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child-safe environment (subset of ``os.environ`` by default).

    Deny-by-default: only passthrough names survive; secret-shaped names
    are dropped even when passthrough-listed.
    """
    source = env if env is not None else dict(os.environ)
    clean: dict[str, str] = {}
    for name, value in source.items():
        upper = name.upper()
        if upper not in _PASSTHROUGH:
            continue
        if is_secret_name(name):
            continue
        clean[name] = value
    return clean


def extend_passthrough(*names: str) -> None:
    """Operator-approved additions to the passthrough set (idempotent)."""
    global _PASSTHROUGH
    merged = set(_PASSTHROUGH)
    for name in names:
        merged.add(name.upper())
    _PASSTHROUGH = tuple(sorted(merged))


def passthrough_names() -> tuple[str, ...]:
    return _PASSTHROUGH


def mask_credential_values(text: str) -> str:
    """Mask credential-shaped substrings in free text (audit/log safety)."""
    return _CREDENTIAL_VALUE_RE.sub("***", text)
