"""Prometheus exposition rendering for the web layer.

``/metrics`` serves ``render_text(REGISTRY)`` verbatim: counters and
gauges as typed samples, histograms as cumulative ``_bucket``/``_count``
/``_sum`` series with ``+Inf`` le labels — a format Prometheus and
vector scrapers parse without conversion.
"""

from __future__ import annotations

import math

from kernel.metrics import MetricsRegistry


def render_text(registry: MetricsRegistry) -> str:
    """Render the registry as a Prometheus exposition string."""
    with registry._lock:   # noqa: SLF001 — same-package render contract
        lines = []
        for name, value in sorted(registry._counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for name, value in sorted(registry._gauges.items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        for name, hist in sorted(registry._histograms.items()):
            lines.append(f"# TYPE {name} histogram")
            for upper, count in hist.cumulative.items():
                label = "+Inf" if math.isinf(upper) else str(upper)
                lines.append(f'{name}_bucket{{le="{label}"}} {count}')
            lines.append(f"{name}_count {hist.count}")
            lines.append(f"{name}_sum {round(hist.total, 6)}")
        return "\n".join(lines) + "\n"
