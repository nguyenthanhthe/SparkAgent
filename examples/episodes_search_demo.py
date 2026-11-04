"""Episodes search demo: goal_contains rendered offline.

The filter behind the episode viewer's search box and the
``/api/episodes?q=`` parameter — case-insensitive goal substring,
composable with the tag filter, driven here against a throwaway SQLite.

    python examples/episodes_search_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.memory import Memory   # noqa: E402


def render(episodes: list[dict]) -> str:
    return "\n".join(f"  #{e['id']} [{e['source']}] {e['goal']}"
                     for e in episodes) or "  (none)"


async def main() -> None:
    memory = Memory(Path(tempfile.mkdtemp()) / "t.db",
                    embedder_fn=None, embed_dim=64)
    await memory.connect()
    for goal in ("audit #security of #web", "write the docs page",
                 "tune #gpu fan curves"):
        eid = await memory.start_episode(goal, "demo")
        await memory.finish_episode(eid, "done", "ok", "local", 1)

    print("all episodes:")
    print(render(await memory.recent_episodes(limit=10)))

    print("\ngoal_contains='gpu':")
    print(render(await memory.recent_episodes(goal_contains="gpu")))

    print("\ngoal_contains='docs':")
    print(render(await memory.recent_episodes(goal_contains="docs")))

    print("\ncombined with tag=#security (AND semantics):")
    print(render(await memory.recent_episodes(goal_contains="audit",
                                              tag="security")))

    print("\nneedle that matches nothing:")
    print(render(await memory.recent_episodes(goal_contains="quantum")))
    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
