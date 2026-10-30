"""Metrics demo: the REGISTRY snapshot rendered as text, fully offline.

Counters, gauges, and a histogram are driven through a synthetic
workload, then REGISTRY.snapshot() is rendered as a human-readable
text report — the same surface /api/metrics and /metrics read.

    python examples/metrics_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.metrics import MetricsRegistry   # noqa: E402


def render(registry: MetricsRegistry) -> str:
    snapshot = registry.snapshot()
    lines = ["metrics snapshot:"]
    for name in sorted(snapshot["counters"]):
        lines.append(f"  counter {name} = {snapshot['counters'][name]:g}")
    for name in sorted(snapshot["gauges"]):
        lines.append(f"  gauge   {name} = {snapshot['gauges'][name]:g}")
    for name, hist in sorted(snapshot["histograms"].items()):
        lines.append(f"  hist    {name} n={hist['count']} "
                     f"p50={hist['p50']:.4f} p95={hist['p95']:.4f}")
    return "\n".join(lines)


def main() -> None:
    registry = MetricsRegistry()
    # a synthetic episode: one success, one failure, one timed tool call
    registry.incr("episodes_done")
    registry.incr("episodes_failed")
    with registry.timed("tool_latency_seconds") as _:
        pass
    registry.gauge("scheduler_inflight", 2)
    registry.gauge("scheduler_blocked", 1)

    print(render(registry))


if __name__ == "__main__":
    main()
