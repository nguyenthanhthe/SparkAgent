"""json_query stats demo: nesting summary over a config-shaped blob.

mode=stats on a nested dict now reports a depth-capped dotted-prefix map
(prefix -> child count), which answers "what does this structure look
like?" before you start pulling paths out of it.

    python examples/json_query_stats_demo.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import stdlib_tools   # noqa: E402
from tools.registry import ToolContext, ToolRegistry   # noqa: E402

CONFIG_LIKE = {
    "agent": {"name": "sparkagent", "poll_seconds": 5},
    "brain": {
        "local": {"model": "nemotron-mini", "num_ctx": 8192},
        "remote": {"model": "glm-5.3", "timeout": 120},
        "fallback_after_failures": 2,
    },
    "memory": {"retention_days": 30, "embedding_model": "nomic-embed"},
    "ops": {"backup_dir": "backups"},
}


async def main() -> None:
    registry = ToolRegistry()
    stdlib_tools.register_tools(registry)
    ctx = ToolContext()

    result = await registry.call(
        "json_query", {"data": json.dumps(CONFIG_LIKE),
                       "mode": "stats"}, ctx)
    print("stats:")
    print(result)
    print("\nnesting says: brain has 3 sections; brain.local has 2 keys — "
          "so 'brain.local.model' is a real path.")

    value = await registry.call(
        "json_query", {"data": json.dumps(CONFIG_LIKE),
                       "mode": "get", "path": "brain.local.model"}, ctx)
    print("get brain.local.model ->", value)


if __name__ == "__main__":
    asyncio.run(main())
