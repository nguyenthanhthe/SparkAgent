"""ReAct core — the agent's think/act/observe state machine.

Protocol: the model replies with EXACTLY one JSON object per turn:

    {"thought": "...", "action": {"name": "tool_name", "args": {...}}}
    {"thought": "...", "final_answer": "..."}

The state machine walks THINK -> ACT -> OBSERVE and back to THINK, with a
parse-repair path (the model gets the parse error as an observation, up to
``max_parse_errors`` times), a step budget, and full persistence of every
step to memory. Relevant long-term memories are injected into the system
context at episode start.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from brain.bridge import Brain
from kernel.bus import EventBus
from kernel.logging import get_logger
from kernel.memory import Memory
from tools.registry import ToolContext, ToolError, ToolRegistry

logger = get_logger("react")

_SYSTEM_TEMPLATE = """\
You are {agent_name}, an autonomous agent running 24/7 on the user's \
local Windows machine. You accomplish goals step by step using tools.

# Tools
{tools_block}

# Response protocol (STRICT)
Reply with EXACTLY ONE JSON object and nothing else — no markdown fences, \
no prose outside the JSON.

To use a tool:
{{"thought": "<your reasoning>", "action": {{"name": "<tool>", "args": {{...}}}}}}

When the goal is fully achieved:
{{"thought": "<your reasoning>", "final_answer": "<complete answer for the user>"}}

# Rules
- One action per turn. Wait for the observation before the next thought.
- Choose the final_answer as soon as the goal is met; do not pad with \
extra tool calls.
- If a tool fails, read the error observation and adapt — different \
arguments, different tool, or a different plan.
- Never fabricate tool output. Never invent tools outside the list.
- Long-term memories (below) may help; ignore them if irrelevant.

# Relevant long-term memories
{memory_block}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
MAX_OBSERVATION_CHARS = 4000
MAX_PARSE_ERRORS = 3


class State(str, Enum):
    THINK = "think"
    ACT = "act"
    OBSERVE = "observe"
    DONE = "done"
    FAILED = "failed"


@dataclass
class EpisodeResult:
    goal: str
    status: str                     # done | failed
    answer: str
    steps: int = 0
    tier: str = ""
    actions: list[dict] = field(default_factory=list)


def extract_json(text: str) -> dict | None:
    """Robustly pull the first balanced JSON object out of model output."""
    if not text:
        return None
    candidates: list[str] = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())
    for candidate in candidates:
        parsed = _try_loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        scanned = _scan_balanced(candidate)
        if scanned is not None:
            parsed = _try_loads(scanned)
            if isinstance(parsed, dict):
                return parsed
    return None


def _try_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _scan_balanced(text: str) -> str | None:
    """Return the first ``{...}`` span with balanced braces outside strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


class ReactAgent:
    def __init__(self, brain: Brain, tools: ToolRegistry, memory: Memory,
                 bus: EventBus, cfg, executor=None, vault=None):
        self.brain = brain
        self.tools = tools
        self.memory = memory
        self.bus = bus
        self.cfg = cfg
        self.executor = executor
        self.vault = vault
        self.agent_name = cfg.get("agent.name", "sparkagent")
        self.max_steps = int(cfg.get("agent.max_steps", 12))

    # ------------------------------------------------------------------ prompt
    def build_system_prompt(self, goal: str) -> str:
        lines = []
        for spec in self.tools.specs():
            params = json.dumps(spec["parameters"], ensure_ascii=False)
            lines.append(f'- {spec["name"]}: {spec["description"]}\n'
                         f'  parameters: {params}')
        return _SYSTEM_TEMPLATE.format(
            agent_name=self.agent_name,
            tools_block="\n".join(lines) or "(no tools registered)",
            memory_block="(memory unavailable at startup)" )

    async def _memory_block(self, goal: str) -> str:
        try:
            hits = await self.memory.recall(goal)
        except Exception as exc:  # noqa: BLE001 — memory must not break an episode
            logger.warning("recall failed: %s", exc)
            return "(recall unavailable)"
        if not hits:
            return "(none)"
        return "\n".join(f"- [{hit.created_at}] ({hit.kind}) {hit.text[:200]}"
                         for hit in hits)

    # ---------------------------------------------------------------- episode
    async def run(self, goal: str, source: str = "operator") -> EpisodeResult:
        goal = goal.strip()
        result = EpisodeResult(goal=goal, status="failed", answer="")
        episode_id = await self.memory.start_episode(goal, source)
        result.actions.append({"episode": "start", "id": episode_id})
        self.bus.publish("logs", f"[agent] episode {episode_id} start "
                                 f"({source}): {goal[:120]}")

        system = self.build_system_prompt(goal)
        system = system.replace(
            "(memory unavailable at startup)", await self._memory_block(goal))
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Goal: {goal}"},
        ]

        state = State.THINK
        step = 0
        parse_errors = 0
        last_tier = ""
        try:
            while step < self.max_steps and state not in (State.DONE, State.FAILED):
                step += 1
                # ---- THINK: ask the model for the next move
                response = await self.brain.chat(messages)
                last_tier = response.tier.value
                parsed = extract_json(response.text)

                if parsed is None:
                    parse_errors += 1
                    if parse_errors >= MAX_PARSE_ERRORS:
                        await self._fail(episode_id, result, step,
                                         f"model output not parseable as JSON "
                                         f"{parse_errors} times; last output: "
                                         f"{response.text[:300]}")
                        return result
                    observation = (
                        "ERROR: your last reply was not a single JSON object. "
                        "Reply again with ONLY the JSON object "
                        '{"thought": ..., "action"/"final_answer": ...}.')
                    await self.memory.log_step(episode_id, step, "parse_error",
                                               response.text[:2000])
                    messages.append({"role": "assistant", "content": response.text})
                    messages.append({"role": "user", "content": f"Observation: {observation}"})
                    continue

                thought = str(parsed.get("thought", ""))[:1500]
                final_answer = parsed.get("final_answer")
                action = parsed.get("action")

                # ---- FINAL
                if isinstance(final_answer, str) and final_answer.strip() and not action:
                    result.status, result.answer = "done", final_answer.strip()
                    result.tier = last_tier
                    await self.memory.log_step(episode_id, step, "final",
                                               final_answer[:4000])
                    break

                # ---- ACT
                if isinstance(action, dict) and action.get("name"):
                    tool_name = str(action["name"])
                    result.actions.append({"step": step, "tool": tool_name})
                    tool_args = action.get("args") or {}
                    if not isinstance(tool_args, dict):
                        tool_args = {"value": tool_args}
                    await self.memory.log_step(
                        episode_id, step, "action",
                        json.dumps({"thought": thought, "tool": tool_name,
                                    "args": tool_args}, ensure_ascii=False,
                                   default=str)[:4000])
                    messages.append({"role": "assistant",
                                     "content": json.dumps(parsed, ensure_ascii=False)})
                    ctx = ToolContext(source="agent", episode_id=episode_id,
                                      executor=self.executor, vault=self.vault,
                                      bus=self.bus, memory=self.memory,
                                      brain=self.brain)
                    try:
                        observation = await self.tools.call(tool_name, tool_args, ctx)
                        observation = f"OK: {observation}"[:MAX_OBSERVATION_CHARS]
                    except ToolError as exc:
                        observation = f"TOOL ERROR: {exc}"[:MAX_OBSERVATION_CHARS]
                    # ---- OBSERVE
                    await self.memory.log_step(episode_id, step, "observation",
                                               observation)
                    messages.append({"role": "user",
                                     "content": f"Observation: {observation}"})
                    continue

                # ---- Neither final nor action: nudge the model
                observation = (
                    'ERROR: JSON must contain either "action" '
                    '{"name","args"} or "final_answer".')
                messages.append({"role": "assistant",
                                 "content": json.dumps(parsed, ensure_ascii=False)})
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                if result.status != "done":
                    await self._fail(episode_id, result, step,
                                     f"reached max_steps={self.max_steps} "
                                     "without a final answer")
                    return result
        except Exception as exc:  # noqa: BLE001 — episode failure, not daemon crash
            logger.exception("episode crashed")
            await self._fail(episode_id, result, step, f"episode crashed: {exc}")
            return result

        result.steps = step
        result.tier = last_tier
        await self.memory.finish_episode(episode_id, result.status, result.answer,
                                         last_tier, step)
        summary = f"Goal: {goal}\nOutcome: {result.answer[:500]}"
        await self.memory.remember(summary, kind="episode", key=f"episode:{episode_id}")
        self.bus.publish("logs", f"[agent] episode {episode_id} {result.status} "
                                 f"in {step} steps ({last_tier})")
        return result

    async def _fail(self, episode_id: int, result: EpisodeResult, step: int,
                    reason: str) -> None:
        result.status, result.steps = "failed", step
        result.answer = reason
        await self.memory.finish_episode(episode_id, "failed", reason,
                                         result.tier or "n/a", step)
        self.bus.publish("logs", f"[agent] episode {episode_id} FAILED: {reason[:200]}")
