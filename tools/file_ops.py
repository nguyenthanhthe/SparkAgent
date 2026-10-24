"""file_ops — read/list/write/stat inside the sandbox roots.

Every path goes through the same :class:`SecurityPolicy.validate_path`
used by skill helpers, so file access stays confined to the allowed
roots regardless of caller. Registered in the tool registry (unlike the
skill-only helpers) so the ReAct core can inspect the sandbox directly.
"""

from __future__ import annotations

from typing import Any

from kernel.errors import ToolFailure
from kernel.validation import require_enum, require_str
from openshell.executor import SafeExecutor
from tools.registry import Tool, ToolContext, ToolRegistry

MAX_READ_BYTES = 65_536
MAX_WRITE_BYTES = 262_144
MAX_LIST_ENTRIES = 500


def register_tools(registry: ToolRegistry, executor: SafeExecutor) -> None:
    policy = executor.policy

    async def file_ops(ctx: ToolContext, operation: str, path: str,
                       content: str = "") -> dict[str, Any]:
        operation = require_enum(operation, "operation",
                                 ["read", "list", "write", "stat"])
        path = require_str(path, "path", max_len=1000)
        resolved = policy.validate_path(path,
                                        write=(operation == "write"))

        if operation == "read":
            if not resolved.is_file():
                raise ToolFailure(f"not a file: {path}")
            data = resolved.read_bytes()
            return {"path": str(resolved),
                    "size": len(data),
                    "truncated": len(data) > MAX_READ_BYTES,
                    "content": data[:MAX_READ_BYTES].decode(
                        "utf-8", errors="replace")}

        if operation == "list":
            if not resolved.exists():
                raise ToolFailure(f"no such directory: {path}")
            entries = []
            for entry in sorted(resolved.iterdir(),
                                key=lambda e: (e.is_file(), e.name.lower())):
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
                try:
                    size = entry.stat().st_size if entry.is_file() else None
                except OSError:
                    size = None
                entries.append({"name": entry.name,
                                "type": "dir" if entry.is_dir() else "file",
                                "size": size})
            return {"path": str(resolved), "entries": entries}

        if operation == "write":
            content = require_str(content, "content", max_len=MAX_WRITE_BYTES)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"path": str(resolved), "bytes_written":
                    len(content.encode("utf-8"))}

        # stat
        if not resolved.exists():
            return {"path": str(resolved), "exists": False}
        stat = resolved.stat()
        return {"path": str(resolved), "exists": True,
                "type": "dir" if resolved.is_dir() else "file",
                "size": stat.st_size,
                "modified": stat.st_mtime}

    registry.register(Tool(
        name="file_ops",
        description=("Read, list, write, or stat files inside the sandbox "
                     "roots. Paths outside the allowed roots are rejected "
                     "by policy. operation: read|list|write|stat; write "
                     "creates parent directories."),
        parameters={
            "operation": {"type": "string", "required": True},
            "path": {"type": "string", "required": True},
            "content": {"type": "string", "required": False},
        },
        handler=file_ops))
