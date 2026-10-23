"""In-process metrics registry: counters, gauges, histograms.

Zero dependencies; fixed log-style buckets keep percentiles cheap and
portable across platforms. ``render_text`` emits a Prometheus exposition
string so ``interface/prom.py`` can serve it verbatim.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5,
                   5.0, 10.0, 30.0)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, "_Histogram"] = {}

    # ---------------------------------------------------------------- counter
    def incr(self, name: str, value: float = 1.0) -> float:
        with self._lock:
            current = self._counters.get(name, 0.0) + value
            self._counters[name] = current
            return current

    def counter(self, name: str) -> float:
        with self._lock:
            return self._counters.get(name, 0.0)

    # ------------------------------------------------------------------ gauge
    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = float(value)

    def gauge_value(self, name: str) -> float | None:
        with self._lock:
            return self._gauges.get(name)

    # -------------------------------------------------------------- histogram
    def observe(self, name: str, value: float,
                buckets: tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        with self._lock:
            hist = self._histograms.get(name)
            if hist is None or hist.buckets != tuple(buckets):
                hist = _Histogram(tuple(buckets))
                self._histograms[name] = hist
            hist.observe(value)

    def histogram(self, name: str) -> dict | None:
        with self._lock:
            hist = self._histograms.get(name)
            return hist.snapshot() if hist else None

    # ----------------------------------------------------------------- timing
    def timed(self, name: str):
        """Context manager recording wall seconds into a histogram."""
        return _Timed(self, name)

    # ---------------------------------------------------------------- render
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {name: hist.snapshot()
                               for name, hist in self._histograms.items()},
            }

    def render_text(self) -> str:
        with self._lock:
            lines = []
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")
            for name, hist in sorted(self._histograms.items()):
                lines.append(f"# TYPE {name} histogram")
                for upper, count in hist.cumulative.items():
                    label = "+Inf" if math.isinf(upper) else str(upper)
                    lines.append(f'{name}_bucket{{le="{label}"}} {count}')
                lines.append(f"{name}_count {hist.count}")
                lines.append(f"{name}_sum {round(hist.total, 6)}")
            return "\n".join(lines) + "\n"


@dataclass
class _Histogram:
    buckets: tuple[float, ...]
    counts: dict[float, int] = field(default_factory=dict)
    count: int = 0
    total: float = 0.0
    _values: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        for bucket in self.buckets:
            self.counts[bucket] = 0
        self.counts[float("inf")] = 0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        self._values.append(value)
        self._values = self._values[-4096:]  # bounded memory
        for upper in self.counts:
            if value <= upper:
                self.counts[upper] += 1

    @property
    def cumulative(self) -> dict[float, int]:
        return {upper: self.counts[upper] for upper in sorted(self.counts)}

    def snapshot(self) -> dict:
        buckets = {"+Inf" if math.isinf(upper) else str(upper): count
                   for upper, count in self.cumulative.items()}
        return {"count": self.count, "sum": round(self.total, 6),
                "buckets": buckets,
                "p50": self.percentile(0.5), "p95": self.percentile(0.95),
                "p99": self.percentile(0.99)}

    def percentile(self, fraction: float) -> float | None:
        if not self._values:
            return None
        ordered = sorted(self._values)
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return ordered[index]


class _Timed:
    def __init__(self, registry: MetricsRegistry, name: str):
        self._registry = registry
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "_Timed":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        elapsed = time.perf_counter() - self._start
        self._registry.observe(self._name, elapsed)


REGISTRY = MetricsRegistry()
