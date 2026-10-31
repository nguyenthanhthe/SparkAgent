"""Score demo: /mem-style ranked output, offline.

The hit formatting the telegram `/mem` command renders — kind and
relevance score prefix, snippet body — over deterministic hits.

    python examples/score_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Hit:
    def __init__(self, kind, score, snippet):
        self.kind = kind
        self.score = score
        self.snippet = snippet


HITS = [Hit("digest", 1.8, "gpu thermal cap is **85c** per operator"),
        Hit("note", 1.2, "gpu thermal logs show throttling at **90c**"),
        Hit("episode", 0.6, "fan curve retuned after the **gpu** swap")]


def render(hits) -> str:
    return "\n\n".join(
        f"[{h.kind} {h.score:.2f}] {h.snippet}" for h in hits)


def main() -> None:
    print(render(HITS))


if __name__ == "__main__":
    main()
