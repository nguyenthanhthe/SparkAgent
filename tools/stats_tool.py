"""Statistics toolkit — descriptive stats, correlation, regression."""

from __future__ import annotations

import math
from typing import Sequence


class StatsError(ValueError):
    pass


def _require(values: Sequence[float], minimum: int = 1) -> list[float]:
    values = [float(v) for v in values]
    if len(values) < minimum:
        raise StatsError(f"need at least {minimum} value(s), got {len(values)}")
    if any(not math.isfinite(v) for v in values):
        raise StatsError("non-finite value in input")
    return values


def mean(values: Sequence[float]) -> float:
    values = _require(values)
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float:
    values = sorted(_require(values))
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


def variance(values: Sequence[float], sample: bool = True) -> float:
    values = _require(values, minimum=2)
    average = mean(values)
    denominator = len(values) - 1 if sample else len(values)
    return sum((v - average) ** 2 for v in values) / denominator


def stdev(values: Sequence[float], sample: bool = True) -> float:
    return math.sqrt(variance(values, sample))


def quantile(values: Sequence[float], fraction: float) -> float:
    if not 0.0 <= fraction <= 1.0:
        raise StatsError("quantile fraction must be in [0, 1]")
    ordered = sorted(_require(values))
    index = fraction * (len(ordered) - 1)
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[int(index)]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def summary(values: Sequence[float]) -> dict[str, float]:
    values = _require(values)
    return {"count": len(values), "mean": round(mean(values), 6),
            "median": round(median(values), 6),
            "min": min(values), "max": max(values),
            "stdev": round(stdev(values), 6) if len(values) > 1 else 0.0,
            "p25": round(quantile(values, 0.25), 6),
            "p75": round(quantile(values, 0.75), 6)}


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    xs, ys = _require(xs, 2), _require(ys, 2)
    if len(xs) != len(ys):
        raise StatsError("inputs must have equal length")
    mx, my = mean(xs), mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs)
                            * sum((y - my) ** 2 for y in ys))
    if denominator == 0:
        raise StatsError("cannot correlate constant series")
    return numerator / denominator


def linear_regression(xs: Sequence[float],
                      ys: Sequence[float]) -> dict[str, float]:
    xs, ys = _require(xs, 2), _require(ys, 2)
    if len(xs) != len(ys):
        raise StatsError("inputs must have equal length")
    mx, my = mean(xs), mean(ys)
    slope_num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope_den = sum((x - mx) ** 2 for x in xs)
    if slope_den == 0:
        raise StatsError("x series is constant; slope undefined")
    slope = slope_num / slope_den
    intercept = my - slope * mx
    fitted = [intercept + slope * x for x in xs]
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return {"slope": round(slope, 8), "intercept": round(intercept, 8),
            "r2": round(r2, 8)}


def moving_average(values: Sequence[float], window: int) -> list[float]:
    values = _require(values)
    if window < 1:
        raise StatsError("window must be >= 1")
    if window > len(values):
        raise StatsError("window larger than series")
    return [round(mean(values[i:i + window]), 6)
            for i in range(len(values) - window + 1)]


def zscore_outliers(values: Sequence[float],
                    threshold: float = 3.0) -> list[dict]:
    """Values whose |z| exceeds threshold (robust: median/MAD based)."""
    values = _require(values, minimum=2)
    center = median(values)
    mad = median([abs(v - center) for v in values]) or 1e-12
    out = []
    for index, value in enumerate(values):
        score = 0.6745 * (value - center) / mad
        if abs(score) > threshold:
            out.append({"index": index, "value": value,
                        "modified_z": round(score, 3)})
    return out
