"""Translate SparkAgent's policy into a draft NVIDIA OpenShell policy.

NVIDIA OpenShell enforces kernel-level confinement from a declared
policy (filesystem, syscalls, processes, network, credential-bound
endpoints). This module renders our own allowlists into that shape so a
SparkAgent deployment can be hardened by exporting the equivalent
sandbox policy rather than maintaining two rule sets by hand.

Honesty note: OpenShell's schema is defined by NVIDIA's docs
(docs.nvidia.com/openshell) and may evolve; the emitted structure is a
faithful DRAFT of our intents and is validated on our side for shape
only. ``apply`` is deliberately left to the operator (or the policy
advisor/prover flow) — SparkAgent never installs policies silently.
"""

from __future__ import annotations

from typing import Any

from openshell.policy import SecurityPolicy

SCHEMA_VERSION = "sparkagent-draft/1"


def translate(policy: SecurityPolicy, sandbox_name: str = "sparkagent",
              description: str = "Exported from SparkAgent policy") \
        -> dict[str, Any]:
    """Render an OpenShell-shaped policy dict from our SecurityPolicy."""
    programs = sorted(policy.allowed_programs)
    roots = [root for root in policy._roots]
    document: dict[str, Any] = {
        "apiVersion": SCHEMA_VERSION,
        "kind": "SandboxPolicy",
        "metadata": {
            "name": sandbox_name,
            "description": description,
        },
        "spec": {
            "process": {
                # exec allowlist mirrors ours; no shell interpretation
                "execAllowlist": programs,
                "shellAllowed": bool(policy.allow_shell),
            },
            "filesystem": {
                # read roots: sandbox + project; writes stay in sandbox
                "readOnly": roots,
                "readWrite": [roots[0]] if roots else [],
                "deny": ["**/.ssh/**", "**/.aws/**", "**/vault.bin"],
            },
            "network": {
                # our webfetch guard is app-level; in-sandbox processes
                # get no egress by default under OpenShell either
                "default": "deny",
                "allow": [],
            },
            "credentials": {
                # never expose secrets inside the sandbox; OpenShell can
                # bind them per-endpoint when an operator adds routes
                "expose": [],
            },
        },
    }
    return document


def render_yaml(document: dict[str, Any], indent: int = 2) -> str:
    """Small deterministic YAML renderer (avoids a pyyaml dump dependency
    mismatch in formatting; round-trips via yaml.safe_load are tested)."""
    import io

    lines = io.StringIO()

    def yaml_escape(text: Any) -> str:
        # double-quoted YAML: escape backslashes (Windows paths) + quotes
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    def emit(value: Any, depth: int) -> None:
        pad = " " * (depth * indent)
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (dict, list)) and item:
                    lines.write(f"{pad}{key}:\n")
                    emit(item, depth + 1)
                elif isinstance(item, (dict, list)):
                    lines.write(f"{pad}{key}: {'{}' if isinstance(item, dict) else '[]'}\n")
                elif isinstance(item, bool):
                    lines.write(f"{pad}{key}: {'true' if item else 'false'}\n")
                elif isinstance(item, (int, float)):
                    lines.write(f"{pad}{key}: {item}\n")
                else:
                    lines.write(f'{pad}{key}: "{yaml_escape(item)}"\n')
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    lines.write(f"{pad}-\n")
                    emit(item, depth + 1)
                else:
                    lines.write(f'{pad}- "{yaml_escape(item)}"\n')

    emit(document, 0)
    return lines.getvalue()


def export_policy_file(policy: SecurityPolicy, path, sandbox_name: str =
                       "sparkagent") -> dict[str, Any]:
    """Write the draft policy to ``path``; returns the document."""
    document = translate(policy, sandbox_name=sandbox_name)
    path.write_text(render_yaml(document), encoding="utf-8")
    return document
