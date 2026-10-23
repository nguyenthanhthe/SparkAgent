"""Generate docs/configuration.md from the DEFAULTS tree.

One source of truth: the shipped defaults. The generator walks the
nested dict and renders a section per top-level key with dotted paths,
defaults, and annotations (hand-written per-path notes). A unit test
re-runs the generator and fails if the committed page drifted.
"""

from __future__ import annotations

from typing import Any

from kernel.config import DEFAULTS

NOTES: dict[str, str] = {
    "agent.max_steps": "ReAct iterations per episode before failing",
    "agent.poll_seconds": "scheduler tick interval",
    "agent.concurrency": "max simultaneous ReAct episodes",
    "agent.heartbeat_seconds": "system snapshot cadence",
    "brain.local.base_url": "Ollama endpoint (Tier 1)",
    "brain.local.model": "local model — `ollama pull <model>`",
    "brain.remote.chat_url": "OpenAI-compatible endpoint (Tier 2)",
    "brain.remote.model": "remote model name",
    "brain.fallback_after_failures": "tier failures before cooldown",
    "brain.vram_guard_mb": "min free VRAM to use Tier 1",
    "brain.daily_budget_usd": "daily remote-tier spend cap (veto)",
    "memory.db_path": "SQLite database location",
    "memory.embedding_model": "Ollama embeddings (falls back to hashing)",
    "memory.retention_days": "episode/step pruning horizon",
    "openshell.allowed_programs": "executable allowlist (bare names)",
    "openshell.execs_per_minute": "per-program rate limit (0 = off)",
    "openshell.profile": "strict | standard | development",
    "tools.webfetch.allowed_ports": "fetchable ports",
    "tools.webfetch.prompt_guard": "scan fetched text for injections",
    "tools.skillforge.autonomous": "skills activate without approval",
    "tools.skillforge.sign_skills": "HMAC-sign skills (needs vault key)",
    "interface.web.host": "dashboard bind (keep 127.0.0.1)",
    "interface.telegram.allowed_chat_ids": "who may command the bot",
    "logging.level": "INFO | DEBUG | json (JSON-lines output)",
}


def _walk(node: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, value in node.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            rows.extend(_walk(value, dotted))
        else:
            rows.append((dotted, value))
    return rows


def generate() -> str:
    lines = [
        "# Configuration reference",
        "",
        "Defaults live in `kernel/config.py`. Overrides: `config.yaml` < "
        "environment (`SPARKAGENT_` prefix, `__` nesting — e.g. "
        "`SPARKAGENT_BRAIN__LOCAL__MODEL`). Credentials never appear here; "
        "they come from env/vault.",
        "",
    ]
    for section in DEFAULTS:
        lines.append(f"## `{section}`")
        lines.append("")
        lines.append("| Path | Default | Notes |")
        lines.append("|---|---|---|")
        for path, default in _walk(DEFAULTS[section], section):
            note = NOTES.get(path, "")
            rendered = f"`{default}`" if not isinstance(default, list) or not \
                default else f"`{default}`"
            lines.append(f"| `{path}` | {rendered} | {note} |")
        lines.append("")
    return "\n".join(lines)


def write_doc(path) -> int:
    text = generate()
    path.write_text(text, encoding="utf-8")
    return len(text.splitlines())


if __name__ == "__main__":
    from pathlib import Path
    lines = write_doc(Path(__file__).resolve().parents[1] / "docs" /
                      "configuration.md")
    print(f"wrote docs/configuration.md ({lines} lines)")
