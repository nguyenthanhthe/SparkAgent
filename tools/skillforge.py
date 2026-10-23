"""SkillForge — the agent writes new tools for itself.

Flow: the model proposes ``{name, description, parameters, code}`` through
the ``skill_create`` tool. SkillForge then:

1. **Static validation** — identifier-safe name; code parsed with ``ast``
   rejecting imports, dunder attribute access, and dangerous builtins
   (eval/exec/compile/open/__import__/…); plus a regex pre-scan and a total
   size cap.
2. **Sandboxed loading** — validated code is persisted to ``skills/<name>.py``
   and loaded through ``importlib`` machinery into a module whose namespace
   is pre-seeded *before* execution: restricted builtins only, and a fixed
   set of stdlib modules (json, re, math, …). Because imports are rejected
   statically and the builtins carry no ``__import__``, the code cannot pull
   in anything outside that namespace. The only I/O is via guarded helpers:
   ``fetch`` (SSRF-guarded), ``read_file``/``write_file``/``list_dir``
   (path-confined, writes sandbox-only), ``run_command`` (OpenShell
   executor), ``log`` (bus).
3. **Approval gate** — by default new skills stay *pending* until an
   operator approves them via the dashboard/Telegram. With
   ``tools.skillforge.autonomous: true`` (or when the request comes from an
   operator) they activate immediately.
4. **Activation** — the skill's ``run(**params)`` (sync or async) is wrapped
   in a timeout and registered in the ToolRegistry; approved skills reload
   automatically on daemon restart through the same loader.

This is a policy sandbox, not a VM — see README "Safety model".
"""

from __future__ import annotations

import ast
import asyncio
import builtins as _builtins
import collections
import datetime
import importlib.machinery
import importlib.util
import inspect
import itertools
import json
import math
import random as _random
import re
import statistics
import string
import textwrap
import time
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from kernel.bus import EventBus
from kernel.logging import get_logger
from openshell.executor import SafeExecutor
from openshell.policy import SecurityError, SecurityPolicy
from tools.registry import Tool, ToolContext, ToolError, ToolRegistry
from tools.webfetch import WebFetcher

logger = get_logger("skillforge")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
MAX_CODE_BYTES = 16 * 1024
MAX_FILE_BYTES = 64 * 1024

_REGEX_DENY: tuple[re.Pattern, ...] = tuple(re.compile(p) for p in (
    r"\bimport\b",
    r"__\w+__",
    r"\b(eval|exec|compile|globals|locals|vars|getattr|setattr|"
    r"delattr|breakpoint|input|exit|quit)\s*\(",
    r"\bopen\s*\(",
    r"\b(os|sys|subprocess|socket|ctypes|shutil|signal|threading|"
    r"multiprocessing|pathlib|urllib|http|requests|aiohttp|asyncio)\.",
))

_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "input", "exit", "quit",
    "__import__", "help",
}

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "bytes", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "hash", "hex",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "oct", "ord", "pow", "range", "repr",
    "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple",
    "zip", "True", "False", "None",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ArithmeticError", "ZeroDivisionError", "StopIteration",
    "RuntimeError", "AttributeError", "LookupError",
)
SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(_builtins, name)
    for name in _SAFE_BUILTIN_NAMES if hasattr(_builtins, name)
}

PROVIDED_MODULES: dict[str, Any] = {
    "json": json, "re": re, "math": math, "statistics": statistics,
    "datetime": datetime, "itertools": itertools, "collections": collections,
    "textwrap": textwrap, "string": string, "uuid": _uuid, "random": _random,
}

META_PREFIX = "# meta:"


class SkillValidationError(Exception):
    pass


@dataclass
class SkillMeta:
    name: str
    description: str
    parameters: dict
    approved: bool
    created_at: str
    source: str


class SkillForge:
    def __init__(self, skills_dir: Path, registry: ToolRegistry,
                 policy: SecurityPolicy, executor: SafeExecutor,
                 bus: EventBus, fetcher: WebFetcher,
                 autonomous: bool = False, exec_timeout: float = 30.0,
                 smoke_test: bool = True):
        self.skills_dir = skills_dir
        self.registry = registry
        self.policy = policy
        self.executor = executor
        self.bus = bus
        self.fetcher = fetcher
        self.autonomous = autonomous
        self.exec_timeout = exec_timeout
        self.smoke_test = smoke_test
        self.pending: dict[str, SkillMeta] = {}
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ validation
    def validate(self, name: str, description: str, parameters: Any,
                 code: str) -> None:
        if not NAME_RE.match(name or ""):
            raise SkillValidationError(
                f"skill name {name!r} must match {NAME_RE.pattern}")
        if not description or len(description) < 10:
            raise SkillValidationError("description too short (min 10 chars)")
        if not isinstance(parameters, dict):
            raise SkillValidationError("parameters must be an object")
        for param, spec in parameters.items():
            if not isinstance(param, str) or not isinstance(spec, dict):
                raise SkillValidationError(
                    f"parameter {param!r} spec must be an object")
        if not code or len(code.encode()) > MAX_CODE_BYTES:
            raise SkillValidationError(f"code empty or larger than {MAX_CODE_BYTES}B")

        for pattern in _REGEX_DENY:
            if pattern.search(code):
                raise SkillValidationError(
                    f"code matches forbidden pattern {pattern.pattern!r}")

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise SkillValidationError(f"code does not parse: {exc}") from exc

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise SkillValidationError(
                    "imports are not allowed — use the provided modules "
                    f"({sorted(PROVIDED_MODULES)})")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                raise SkillValidationError(f"forbidden name {node.id!r} used")
            if isinstance(node, ast.Attribute) and (
                    node.attr.startswith("__")
                    or node.attr in {"system", "popen", "fdopen", "spawn"}):
                raise SkillValidationError(
                    f"forbidden attribute access .{node.attr}")

        if "run" not in code:
            raise SkillValidationError("code must define a function 'run'")

    # -------------------------------------------------------------- lifecycle
    def propose(self, name: str, description: str, parameters: Any,
                code: str, source: str) -> dict[str, Any]:
        self.validate(name, description, parameters, code)
        approved = self.autonomous or source == "operator"
        meta = SkillMeta(name=name, description=description,
                         parameters=parameters or {}, approved=approved,
                         created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                         source=source)
        self._persist(meta, code)
        if approved:
            self.activate(meta)
            return {"skill": name, "status": "active"}
        self.pending[name] = meta
        self.bus.publish("audit", {
            "actor": "skillforge", "action": "skill.pending",
            "detail": f"{name} awaiting operator approval"})
        return {"skill": name, "status": "pending_approval"}

    def approve(self, name: str, source: str) -> dict[str, Any]:
        if source != "operator":
            raise ToolError("only operators can approve skills "
                            "(use the dashboard or Telegram)")
        meta = self.pending.pop(name, None)
        if meta is None:
            raise ToolError(f"no pending skill named {name!r}")
        meta.approved = True
        code = self._read_code(name)
        self._persist(meta, code)
        self.activate(meta)
        return {"skill": name, "status": "active"}

    def activate(self, meta: SkillMeta) -> None:
        """Load the persisted skill module and register it as a tool."""
        module = self._load_module(meta.name)
        run_fn = getattr(module, "run", None)
        if not callable(run_fn):
            raise SkillValidationError("skill module must define 'run'")
        if self.smoke_test:
            self._smoke_test(meta, run_fn)
        forge = self

        async def handler(ctx: ToolContext, **kwargs: Any) -> Any:
            return await forge._execute(meta.name, run_fn, kwargs)

        self.registry.register(Tool(
            name=meta.name, description=meta.description,
            parameters=meta.parameters, handler=handler, source="skill"))
        logger.info("skill activated: %s", meta.name)

    async def _execute(self, name: str, run_fn: Callable, kwargs: dict) -> Any:
        try:
            if inspect.iscoroutinefunction(run_fn):
                return await asyncio.wait_for(run_fn(**kwargs), self.exec_timeout)
            return await asyncio.wait_for(
                asyncio.to_thread(run_fn, **kwargs), self.exec_timeout)
        except asyncio.TimeoutError as exc:
            raise ToolError(f"skill {name!r} exceeded {self.exec_timeout}s "
                            "limit") from exc

    def _smoke_test(self, meta: SkillMeta, run_fn: Callable) -> None:
        """Call the skill once with synthesized args; reject broken skills.

        Runs on a dedicated daemon thread with its own event loop (never
        the caller's loop — activation is sync and must not deadlock it),
        joined with a wall timeout. Sandbox-guard rejections count as a
        PASS: the guard firing on placeholder args proves wiring, not a
        broken skill. Args come from the parameter spec: strings get
        "smoke", integers 1, numbers 1.0, objects {}.

        Residual (documented): a skill stuck in an unkillable CPU loop
        leaks its daemon thread — the same thread-leak class as any
        timeout-cancelled ``_execute`` call.
        """
        from openshell.policy import SecurityError
        args: dict[str, Any] = {}
        for param, rule in meta.parameters.items():
            kind = rule.get("type", "string")
            if not rule.get("required"):
                continue
            if kind == "integer":
                args[param] = 1
            elif kind == "number":
                args[param] = 1.0
            elif kind == "object":
                args[param] = {}
            else:
                args[param] = "smoke"

        outcome: dict[str, Any] = {}

        def runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                outcome["value"] = loop.run_until_complete(
                    self._execute(meta.name, run_fn, args))
            except SecurityError as exc:
                outcome["guard"] = str(exc)      # sandbox worked — acceptable
            except BaseException as exc:        # noqa: BLE001 — recorded
                outcome["error"] = exc
            finally:
                loop.close()

        import threading
        thread = threading.Thread(target=runner, daemon=True,
                                  name=f"smoke-{meta.name}")
        thread.start()
        thread.join(self.exec_timeout + 5)
        if thread.is_alive():
            raise SkillValidationError(
                "smoke test timed out — skill rejected")
        if "guard" in outcome:
            logger.info("smoke test: sandbox guard fired for %s (%s) — "
                        "accepted", meta.name, outcome["guard"][:60])
            return
        if "error" in outcome:
            exc = outcome["error"]
            raise SkillValidationError(
                f"smoke test failed: {type(exc).__name__}: {exc}") from exc
        logger.info("smoke test passed for skill %s -> %s",
                    meta.name, str(outcome.get("value"))[:60])

    # ------------------------------------------------------------- namespace
    def _load_module(self, name: str) -> ModuleType:
        """Load ``skills/<name>.py`` into a restricted namespace.

        The module dict is fully seeded (safe builtins, provided modules,
        guarded helpers) *before* the source executes, and contains no
        ``__import__``, so the loaded code cannot escape the sandbox
        (everything it can reach is what we put there).
        """
        source = self.skills_dir / f"{name}.py"
        if not source.exists():
            raise SkillValidationError(f"skill file missing: {source}")
        module_name = f"skills.{name}"
        loader = importlib.machinery.SourceFileLoader(module_name, str(source))
        spec = importlib.util.spec_from_loader(module_name, loader)
        module = importlib.util.module_from_spec(spec)
        module.__dict__.update(PROVIDED_MODULES)
        module.__dict__.update(self._helpers())
        module.__dict__["__builtins__"] = dict(SAFE_BUILTINS)
        try:
            loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — surfaced as validation error
            raise SkillValidationError(
                f"skill raised at load time: {type(exc).__name__}: {exc}") from exc
        return module

    def _helpers(self) -> dict[str, Any]:
        async def fetch(url: str) -> Any:
            return await self.fetcher.fetch(url)

        def read_file(path: str) -> str:
            resolved = self.policy.validate_path(path, write=False)
            data = resolved.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                raise ValueError("file too large to read into a skill")
            return data.decode("utf-8", errors="replace")

        def write_file(path: str, content: str) -> str:
            if len(content.encode()) > MAX_FILE_BYTES:
                raise ValueError("content too large")
            resolved = self.policy.validate_path(path, write=True)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return f"wrote {len(content)} chars to {resolved.name}"

        def list_dir(path: str = ".") -> list:
            resolved = self.policy.validate_path(path, write=False)
            return sorted(entry.name + ("/" if entry.is_dir() else "")
                          for entry in resolved.iterdir())

        async def run_command(program: str, *args: str) -> dict[str, Any]:
            result = await self.executor.run(program, list(args))
            return {"ok": result.ok, "exit_code": result.exit_code,
                    "stdout": result.stdout, "stderr": result.stderr,
                    "blocked": result.blocked_reason}

        def log(message: str) -> None:
            self.bus.publish("logs", f"[skill] {message}")

        return {"fetch": fetch, "read_file": read_file, "write_file": write_file,
                "list_dir": list_dir, "run_command": run_command, "log": log}

    # ------------------------------------------------------------ persistence
    def _persist(self, meta: SkillMeta, code: str) -> None:
        header = ("# --- SparkAgent skill (auto-generated) ---\n"
                  f"{META_PREFIX} {json.dumps(meta.__dict__, ensure_ascii=False)}\n")
        (self.skills_dir / f"{meta.name}.py").write_text(header + code,
                                                         encoding="utf-8")

    def _read_code(self, name: str) -> str:
        text = (self.skills_dir / f"{name}.py").read_text(encoding="utf-8")
        return text.split("\n", 2)[2] if text.startswith("# ---") else text

    def load_persisted(self) -> dict[str, int]:
        """Reload skills from disk at daemon startup."""
        loaded = {"active": 0, "pending": 0}
        for path in sorted(self.skills_dir.glob("*.py")):
            try:
                meta_line = next((line for line in
                                  path.read_text(encoding="utf-8").splitlines()
                                  if line.startswith(META_PREFIX)), None)
                if not meta_line:
                    continue
                meta = SkillMeta(**json.loads(meta_line[len(META_PREFIX):]))
                if meta.approved:
                    self.activate(meta)
                    loaded["active"] += 1
                else:
                    self.pending[meta.name] = meta
                    loaded["pending"] += 1
            except Exception as exc:  # noqa: BLE001 — one bad skill can't stop boot
                logger.error("failed to load skill %s: %s", path.name, exc)
        return loaded

    def list_skills(self) -> list[dict]:
        skills = [{"name": tool.name, "status": "active", "source": tool.source}
                  for tool in self.registry._tools.values()
                  if tool.source == "skill"]
        skills += [{"name": name, "status": "pending_approval", "source": "pending"}
                   for name in sorted(self.pending)]
        return skills


# ------------------------------------------------------------------- tool API
def register_tools(registry: ToolRegistry, forge: SkillForge) -> None:
    async def skill_create(ctx: ToolContext, name: str, description: str,
                           parameters: dict, code: str) -> dict:
        return forge.propose(name, description, parameters or {}, code,
                             source=ctx.source)

    registry.register(Tool(
        name="skill_create",
        description=("Create a new tool for yourself. code must define "
                     "run(**params) using ONLY provided modules (json, re, "
                     "math, statistics, datetime, itertools, collections, "
                     "textwrap, string, uuid, random) and helpers "
                     "(fetch(url), read_file(path), write_file(path, content), "
                     "list_dir(path), run_command(program, *args), log(msg)). "
                     "No imports, no open(), no eval. Writes stay in the "
                     "sandbox. New skills need operator approval unless "
                     "autonomous mode is on."),
        parameters={
            "name": {"type": "string", "required": True,
                     "desc": "snake_case tool name"},
            "description": {"type": "string", "required": True,
                            "desc": "what the tool does (shown in your tool list)"},
            "parameters": {"type": "object", "required": True,
                           "desc": 'param spec e.g. {"text": {"type": "string", '
                                   '"required": true}}'},
            "code": {"type": "string", "required": True,
                     "desc": "python source defining run(**params)"},
        },
        handler=skill_create, dangerous=True))

    async def skill_list(ctx: ToolContext) -> list:
        return forge.list_skills()

    registry.register(Tool(
        name="skill_list",
        description="List all skills (active and pending approval).",
        parameters={}, handler=skill_list))

    async def skill_approve(ctx: ToolContext, name: str) -> dict:
        return forge.approve(name, source=ctx.source)

    registry.register(Tool(
        name="skill_approve",
        description="Approve a pending skill so it becomes callable. "
                    "Operator-only.",
        parameters={"name": {"type": "string", "required": True}},
        handler=skill_approve, dangerous=True))
