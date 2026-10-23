"""Micro-benchmarks for SparkAgent's hot paths.

``python -m benchmarks.bench [--quick]`` prints ops/sec for the hashing
embedder, BM25 indexing/search, ReAct JSON extraction, context budgeting,
and policy validation. Not a CI gate — a regression radar: numbers should
stay in the same order of magnitude across changes.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from kernel.memory import HashingEmbedder
from kernel.react import extract_json
from kernel.validation import require_str
from openshell.policy import SecurityPolicy
from memory_search.bm25 import BM25Index
from brain.context import ContextBudget, Part


@dataclass
class BenchResult:
    name: str
    iterations: int
    seconds: float

    @property
    def ops_per_second(self) -> float:
        return self.iterations / self.seconds if self.seconds else 0.0

    def line(self) -> str:
        return (f"{self.name:<36} {self.iterations:>7} ops "
                f"{self.seconds * 1000:>8.1f} ms  "
                f"{self.ops_per_second:>10.0f} ops/s")


def timeit(name: str, fn, iterations: int) -> BenchResult:
    fn()  # warm-up
    started = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - started
    return BenchResult(name, iterations, elapsed)


def make_documents(count: int) -> list[tuple[str, str]]:
    words = ["gpu", "memory", "thermal", "agent", "kernel", "sandbox",
             "vector", "task", "skill", "quota", "vram", "ollama"]
    docs = []
    for index in range(count):
        text = " ".join(words[(index + offset) % len(words)]
                        for offset in range(20))
        docs.append((f"doc-{index}", text))
    return docs


def run(quick: bool = False) -> list[BenchResult]:
    scale = 1 if quick else 5
    results = []

    embedder = HashingEmbedder(384)
    results.append(timeit(
        "hashing embedder (200ch text)",
        lambda: embedder.embed("gpu thermal throttle " * 8), 2000 * scale))

    docs = make_documents(200 * scale)
    index = BM25Index()

    def build():
        fresh = BM25Index()
        for doc_id, text in docs:
            fresh.add(doc_id, text)
    results.append(timeit(f"bm25 index build ({len(docs)} docs)", build, 5))

    for doc_id, text in docs:
        index.add(doc_id, text)
    results.append(timeit(
        "bm25 search (10 docs)", lambda: index.search("gpu thermal", 10),
        500 * scale))

    payloads = [
        '{"thought": "analyze", "action": {"name": "web_fetch", '
        '"args": {"url": "http://x"}}}',
        '```json\n{"final_answer": "done and summarized"}\n```',
        'prose around {"thought": "t", "final_answer": "a"} more prose',
    ]
    results.append(timeit(
        "react json extraction",
        lambda: [extract_json(p) for p in payloads], 1000 * scale))

    budget = ContextBudget(window_tokens=8000)

    def fit():
        budget.fit([Part("system", "s" * 200, priority=1000,
                         shrinkable=False),
                    Part("goal", "g" * 200, priority=900, shrinkable=False),
                    Part("mem", "m" * 2000, priority=100)])
    results.append(timeit("context budget fit", fit, 2000 * scale))

    import tempfile
    from pathlib import Path
    sandbox = Path(tempfile.mkdtemp())
    policy = SecurityPolicy(["python", "git"], [sandbox], sandbox)
    results.append(timeit(
        "policy validation (allow)",
        lambda: policy.validate_command("git", ["status"]), 20000 * scale))
    results.append(timeit(
        "policy validation (escape deny)",
        lambda: _expect_denied(policy), 5000 * scale))
    return results


def _expect_denied(policy: SecurityPolicy) -> None:
    try:
        policy.validate_command("python", ["../../x.py"])
    except Exception:  # noqa: BLE001 — expected
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="smaller iteration counts")
    args = parser.parse_args()
    print(f"SparkAgent micro-benchmarks (quick={args.quick})")
    print("-" * 72)
    for result in run(quick=args.quick):
        print(result.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
