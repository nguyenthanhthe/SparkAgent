"""Topology demo: all five swarm composition shapes with stub functions.

Runs each topology offline against deterministic fake agents and prints
the outputs plus the mermaid diagram served at ``GET /api/swarm``:

    python examples/topology_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarm.render import topology_catalog    # noqa: E402
from swarm.topologies import (map_reduce, parallel,  # noqa: E402
                              sequential, star)


async def main() -> None:
    async def stage_a(goal, context):
        return "temperature: 71C"

    async def stage_b(goal, context):
        return f"{context} -> within thermal budget"

    async def worker(name, goal, context):
        return f"[{name}] load 62%, nominal"

    async def merge(goal, combined):
        return combined.replace("\n\n", " | ")

    async def hub(goal, context):
        return f"hub ({context[:40]}...)"

    async def mapper(item, context):
        return f"{item}: ok"

    async def reducer(items, context):
        return f"{len(items)} checks passed: {', '.join(items)}"

    report = await sequential("check gpu", [("measure", stage_a),
                                            ("assess", stage_b)])
    print("sequential :", report.output)

    report = await parallel("check gpu", [("probe1", lambda g, c: worker(
        "probe1", g, c)), ("probe2", lambda g, c: worker("probe2", g, c))],
        merge=merge)
    print("parallel   :", report.output)

    report = await star("check gpu", hub=hub,
                        spokes=[("s1", stage_a), ("s2", stage_b)])
    print("star       :", report.output[:80])

    report = await map_reduce(
        "check gpu", ["thermals", "vram", "fan"],
        mapper=mapper, reducer=reducer)
    print("map_reduce :", report.output)

    print()
    for entry in topology_catalog():
        print(f"--- {entry['name']}: {entry['description']}")
        print(entry["mermaid"])
        print()


if __name__ == "__main__":
    asyncio.run(main())
