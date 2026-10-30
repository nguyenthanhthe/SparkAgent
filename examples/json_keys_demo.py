"""Keys demo: json_query mode=keys with a case-insensitive prefix.

The 'what's in this object?' surface — top-level keys mapped to their
value types, narrowed by a prefix — over the same document the agent
sees when inspecting an API response.

    python examples/json_keys_demo.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.json_tool import top_keys   # noqa: E402

DOC = {"gpu_temp": 72, "gpu_fans": 41, "gpu_model": "RTX 4090",
       "cpu_temp": 55, "cpu_cores": 24, "uptime_s": 86400}


def main() -> None:
    print("all keys:")
    for key, kind in top_keys(DOC).items():
        print(f"  {key:12s} {kind}")

    print("\nprefix 'gpu':")
    for key, kind in top_keys(DOC, prefix="gpu").items():
        print(f"  {key:12s} {kind}")

    print("\nprefix 'GPU' (case-insensitive):")
    print(f"  {json.dumps(top_keys(DOC, prefix='GPU'))}")

    print("\nprefix 'net' (no match):")
    print(f"  {json.dumps(top_keys(DOC, prefix='net'))}")


if __name__ == "__main__":
    main()
