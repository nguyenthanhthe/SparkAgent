"""Tool registry — how the ReAct core calls capabilities.

Handlers are async callables ``handler(ctx, **args)``. The registry validates
required parameters, converts exceptions into ``ToolError`` messages (which
become observations the model can react to), truncates oversized results,
and publishes an audit event for every call.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from kernel.bus import EventBus
from kernel.errors import ToolFailure
from kernel.logging import get_logger

logger = get_logger("tools")

Handler = Callable[..., Awaitable[Any] | Any]

MAX_RESULT_CHARS = 8000

# Single tool-error type across the framework: handlers may raise either
# alias; the registry passes it through as a model-facing observation.
ToolError = ToolFailure


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, dict] = field(default_factory=dict)
    handler: Handler | None = None
    dangerous: bool = False
    source: str = "builtin"  # builtin | skill

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "parameters": self.parameters, "dangerous": self.dangerous,
                "source": self.source}


@dataclass
class ToolContext:
    """Everything a tool may need from the runtime, injected per call."""
    source: str = "agent"            # agent | operator (web/telegram)
    episode_id: int | None = None
    executor: Any = None             # openshell.SafeExecutor
    vault: Any = None                # openshell.SecretVault
    bus: EventBus | None = None
    memory: Any = None               # kernel.memory.Memory
    brain: Any = None                # brain.Brain
    extras: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self, bus: EventBus | None = None):
        self._tools: dict[str, Tool] = {}
        self.bus = bus

    # --------------------------------------------------------------- register
    def register(self, tool: Tool) -> None:
        if tool.handler is None:
            raise ValueError(f"tool {tool.name!r} has no handler")
        if not tool.name.isidentifier():
            raise ValueError(f"tool name must be an identifier: {tool.name!r}")
        replacing = tool.name in self._tools
        self._tools[tool.name] = tool
        logger.info("registered tool %s (%s)%s", tool.name, tool.source,
                    " [replaced]" if replacing else "")

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[dict]:
        return [tool.spec() for tool in self._tools.values()]

    def tool(self, name: str, description: str,
             parameters: dict[str, dict] | None = None,
             dangerous: bool = False):
        """Decorator: @registry.tool("name", "desc", {...})."""
        def decorator(fn: Handler) -> Handler:
            self.register(Tool(name=name, description=description,
                               parameters=parameters or {}, handler=fn,
                               dangerous=dangerous))
            return fn
        return decorator

    # ------------------------------------------------------------------- call
    async def call(self, name: str, args: dict[str, Any] | None,
                   ctx: ToolContext) -> str:
        args = dict(args or {})
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(self.names()) or "(none)"
            raise ToolError(f"unknown tool {name!r}. Available tools: {known}")

        missing = [param for param, spec in tool.parameters.items()
                   if spec.get("required") and param not in args]
        if missing:
            raise ToolError(f"missing required parameter(s) {missing} for tool "
                            f"{name!r} (expected: {tool.parameters})")

        audit_detail = {"tool": name, "source": ctx.source,
                        "args": _safe_args(tool, args)}
        if self.bus is not None:
            self.bus.publish("audit", {"actor": f"tool:{name}",
                                       "action": "call",
                                       "detail": json.dumps(audit_detail)[:500]})

        from kernel.metrics import REGISTRY as metrics
        import time as _time
        started = _time.perf_counter()
        try:
            result = tool.handler(ctx, **args)
            if inspect.isawaitable(result):
                result = await result
        except ToolError as exc:
            metrics.observe("tool_seconds", _time.perf_counter() - started)
            metrics.incr(f"tool_{name}_errors_total")
            raise
        except TypeError as exc:
            raise ToolError(f"bad arguments for tool {name!r}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — errors become observations
            logger.error("tool %s crashed: %s\n%s", name, exc,
                         traceback.format_exc())
            metrics.incr(f"tool_{name}_crashes_total")
            raise ToolError(f"tool {name!r} crashed: {type(exc).__name__}: "
                            f"{exc}") from exc
        finally:
            metrics.incr(f"tool_{name}_total")

        metrics.observe("tool_seconds", _time.perf_counter() - started)
        return _stringify(result, MAX_RESULT_CHARS)


def _safe_args(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """Mask values of parameters flagged secret:true in the audit trail."""
    safe = {}
    for key, value in args.items():
        if tool.parameters.get(key, {}).get("secret"):
            safe[key] = "***"
        else:
            safe[key] = value
    return safe


def _stringify(result: Any, limit: int) -> str:
    if result is None:
        return "ok"
    if isinstance(result, str):
        text = result
    elif isinstance(result, (dict, list)):
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(result)
    else:
        text = str(result)
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n...[truncated]...\n" + text[-limit // 4:]
