"""Swarm topologies — reusable composition patterns for agent functions.

Each topology takes injected async functions and wires them into a
coordination shape:

- ``sequential`` — pipeline: each stage's output feeds the next context
- ``parallel``  — fan-out on the same input, then a merge function
- ``star``      — hub routes the input to every spoke, aggregates replies
- ``debate``    — one function, alternating pro/con perspectives
- ``map_reduce``— mapper over items, reducer folds results
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Fn = Callable[[str, str], Awaitable[str]]


@dataclass
class TopologyResult:
    output: str
    stages: list[dict[str, Any]] = field(default_factory=list)

    def note(self, stage: str, **data: Any) -> None:
        self.stages.append({"stage": stage, **data})


async def sequential(goal: str, stages: list[tuple[str, Fn]]) -> TopologyResult:
    """Run named stages in order; each receives the previous output."""
    result = TopologyResult(output=goal)
    context = ""
    for name, fn in stages:
        output = await fn(goal, context)
        result.note(name, output=output[:200])
        context = output
    if stages:
        result.output = context        # zero stages: pass the goal through
    return result


async def parallel(goal: str, workers: list[tuple[str, Fn]],
                   merge: Fn | None = None,
                   concurrency: int = 4) -> TopologyResult:
    """Every worker answers the same goal; optionally merge the outputs."""
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(name: str, fn: Fn) -> tuple[str, str]:
        async with semaphore:
            try:
                return name, await fn(goal, "")
            except Exception as exc:  # noqa: BLE001 — isolate workers
                return name, f"({name} failed: {exc})"

    pairs = await asyncio.gather(*(run_one(name, fn)
                                   for name, fn in workers))
    result = TopologyResult(output="")
    for name, output in pairs:
        result.note(name, output=output[:200])
    if merge is not None:
        combined = "\n\n".join(f"[{name}]\n{text}" for name, text in pairs)
        result.output = await merge(goal, combined)
    else:
        result.output = "\n\n".join(f"[{name}]\n{text}" for name, text in pairs)
    return result


async def star(goal: str, hub: Fn, spokes: list[tuple[str, Fn]]) \
        -> TopologyResult:
    """Hub summarizes its routing, spokes answer, hub aggregates."""
    result = TopologyResult(output="")
    routing = await hub(goal, f"route to {len(spokes)} spokes")
    result.note("hub.routing", output=routing[:200])
    replies = await asyncio.gather(
        *(fn(goal, routing) for _, fn in spokes), return_exceptions=True)
    payloads = []
    for (name, _fn), reply in zip(spokes, replies):
        if isinstance(reply, Exception):
            result.note(name, error=str(reply))
            payloads.append(f"[{name}] failed: {reply}")
        else:
            result.note(name, output=reply[:200])
            payloads.append(f"[{name}]\n{reply}")
    result.output = await hub(goal, "aggregate:\n" + "\n\n".join(payloads))
    return result


async def debate(goal: str, fn: Fn, rounds: int = 2) -> TopologyResult:
    """Alternate proponent/opponent perspectives, then settle."""
    result = TopologyResult(output="")
    transcript = ""
    for round_index in range(rounds):
        pro = await fn(goal, f"Argue FOR this answer. Transcript so far:\n"
                             f"{transcript}")
        con = await fn(goal, f"Argue AGAINST or refine. Transcript:\n{pro}")
        transcript = f"{pro}\n\n---\n\n{con}"
        result.note(f"round_{round_index + 1}", pro=pro[:120],
                    con=con[:120])
    result.output = await fn(goal, f"Settle the debate fairly:\n{transcript}")
    return result


async def map_reduce(goal: str, items: list[str], mapper: Fn, reducer: Fn,
                     concurrency: int = 4) -> TopologyResult:
    """Map each item, then reduce the mapped outputs into one answer."""
    semaphore = asyncio.Semaphore(concurrency)

    async def map_one(item: str) -> str:
        async with semaphore:
            try:
                return await mapper(item, f"parent goal: {goal}")
            except Exception as exc:  # noqa: BLE001
                return f"(map failed: {exc})"

    mapped = list(await asyncio.gather(*(map_one(item) for item in items)))
    result = TopologyResult(output="")
    for item, output in zip(items, mapped):
        result.note("map", item=item[:80], output=output[:120])
    result.output = await reducer(goal, "\n\n".join(mapped))
    return result
