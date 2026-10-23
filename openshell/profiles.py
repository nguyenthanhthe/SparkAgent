"""Named OpenShell policy profiles.

Different trust levels need different guardrails. ``strict`` allows only
read-only introspection; ``standard`` is the default dev-agent profile;
``development`` additionally permits package managers (network installs).
Profiles are data — they construct a :class:`SecurityPolicy` with roots
confined appropriately and can be extended from config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openshell.policy import SecurityPolicy

PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "strict": {
        "allowed_programs": ["python", "where", "tasklist"],
        "allow_shell": False,
        "timeout": 30.0,
        "writable": False,          # arguments may not reference project root
    },
    "standard": {
        "allowed_programs": ["python", "py", "pip", "git", "node", "npm",
                             "nvidia-smi", "where", "tasklist", "systeminfo"],
        "allow_shell": False,
        "timeout": 60.0,
        "writable": True,
    },
    "development": {
        "allowed_programs": ["python", "py", "pip", "git", "node", "npm",
                             "npx", "nvidia-smi", "where", "tasklist",
                             "systeminfo"],
        "allow_shell": False,
        "timeout": 300.0,
        "writable": True,
    },
}

VALID_PROFILES = tuple(PROFILE_DEFAULTS)


class UnknownProfile(ValueError):
    pass


def build_policy(profile: str, sandbox_root: Path,
                 project_root: Path, **overrides: Any) -> SecurityPolicy:
    """Construct a SecurityPolicy from a named profile + overrides."""
    if profile not in PROFILE_DEFAULTS:
        raise UnknownProfile(
            f"unknown profile {profile!r}; valid: {VALID_PROFILES}")
    settings = dict(PROFILE_DEFAULTS[profile])
    settings.update(overrides)

    allowed_roots: list[Path] = [sandbox_root]
    if settings["writable"]:
        allowed_roots.append(project_root)

    return SecurityPolicy(
        allowed_programs=settings["allowed_programs"],
        allowed_roots=allowed_roots,
        sandbox_root=sandbox_root,
        allow_shell=bool(settings["allow_shell"]))


def describe_profiles() -> list[dict[str, Any]]:
    return [{"name": name,
             "allowed_programs": values["allowed_programs"],
             "allow_shell": values["allow_shell"],
             "timeout": values["timeout"],
             "project_root_accessible": values["writable"]}
            for name, values in PROFILE_DEFAULTS.items()]
