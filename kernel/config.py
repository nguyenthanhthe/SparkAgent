"""Configuration loading: built-in defaults < config.yaml < environment.

Environment overrides use the prefix ``SPARKAGENT_`` and a double underscore
as the nesting separator, e.g. ``SPARKAGENT_BRAIN__LOCAL__MODEL=llama3``.
Values are parsed as YAML scalars so numbers and booleans round-trip.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ENV_PREFIX = "SPARKAGENT_"
ENV_SEPARATOR = "__"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULTS: dict[str, Any] = {
    "agent": {
        "name": "sparkagent",
        "max_steps": 12,
        "poll_seconds": 5,
        "concurrency": 2,
        "heartbeat_seconds": 30,
    },
    "brain": {
        "local": {
            "enabled": True,
            "base_url": "http://127.0.0.1:11434",
            "model": "nemotron-mini",
            "timeout": 180.0,
            "num_ctx": 8192,
            "temperature": 0.4,
        },
        "remote": {
            "enabled": True,
            "chat_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            "model": "glm-5.3",
            "timeout": 120.0,
            "temperature": 0.4,
        },
        "fallback_after_failures": 2,
        "vram_guard_mb": 1024,
        "health_ttl": 30.0,
        "daily_budget_usd": 5.0,
        "cache_responses": False,
        "cache_entries": 256,
        "cache_ttl": 900.0,
    },
    "memory": {
        "db_path": "data/sparkagent.db",
        "embedding_model": "nomic-embed-text",
        "embed_dim": 384,
        "recall_k": 5,
        "retention_days": 30,
    },
    "openshell": {
        "timeout": 60.0,
        "max_output_bytes": 131072,
        "allow_shell": False,
        "execs_per_minute": 30.0,
        "profile": "standard",
        "backend": "auto",
        "sandbox_name": "sparkagent",
        "minimum_version": "0.1.0",
        "allowed_programs": [
            "python", "py", "pip", "git", "node", "npm",
            "nvidia-smi", "where", "tasklist", "systeminfo",
        ],
    },
    "tools": {
        "webfetch": {
            "max_bytes": 2097152,
            "timeout": 30.0,
            "allowed_ports": [80, 443, 8080, 8443],
            "max_chars": 6000,
            "prompt_guard": True,
        },
        "skillforge": {"autonomous": False, "exec_timeout": 30.0,
                       "sign_skills": True},
    },
    "interface": {
        "web": {"enabled": True, "host": "127.0.0.1", "port": 8788},
        "telegram": {"enabled": False, "allowed_chat_ids": []},
    },
    "logging": {"level": "INFO", "file": "data/logs/sparkagent.log"},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` and return a new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _set_nested(data: dict[str, Any], path: list[str], value: Any) -> None:
    node = data
    for part in path[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[path[-1]] = value


class Config:
    """Read-only view over the merged configuration tree."""

    def __init__(self, data: dict[str, Any], root: Path = PROJECT_ROOT):
        self._data = data
        self.root = root

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: str | Path | None = None,
             root: Path = PROJECT_ROOT) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        if path is not None:
            file = Path(path)
            if not file.exists():
                raise FileNotFoundError(f"config file not found: {file}")
            with open(file, "r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"config root must be a mapping: {file}")
            data = deep_merge(data, loaded)
        data = cls._apply_env(data)
        return cls(data, root=root)

    @staticmethod
    def _apply_env(data: dict[str, Any]) -> dict[str, Any]:
        data = copy.deepcopy(data)
        for raw_key, raw_value in os.environ.items():
            if not raw_key.startswith(ENV_PREFIX) or ENV_SEPARATOR not in raw_key:
                continue
            path = raw_key[len(ENV_PREFIX):].lower().split(ENV_SEPARATOR)
            if not all(path):
                continue
            try:
                parsed: Any = yaml.safe_load(raw_value)
            except yaml.YAMLError:
                parsed = raw_value
            _set_nested(data, path, parsed if parsed is not None else raw_value)
        return data

    # ----------------------------------------------------------------- access
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, dotted: str) -> dict[str, Any]:
        value = self.get(dotted, {})
        return value if isinstance(value, dict) else {}

    @property
    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    # ------------------------------------------------------------------ paths
    def path(self, value: str | Path) -> Path:
        """Resolve a configured path relative to the project root."""
        path = Path(value)
        return path if path.is_absolute() else (self.root / path)

    def ensure_dirs(self) -> None:
        """Create every runtime directory SparkAgent writes to."""
        for key in ("data", "data/logs", "data/sandbox", "skills"):
            (self.root / key).mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.path(self.get("memory.db_path", "data/sparkagent.db"))

    @property
    def sandbox_root(self) -> Path:
        return self.root / "data" / "sandbox"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"
