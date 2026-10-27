"""Token usage and cost accounting.

Prices are USD per 1M tokens, declared per model with wildcard fallbacks
(``glm-*``, ``gpt-4o-*``). ``CostTracker`` accumulates per model/tier/day
from adapter responses so the dashboard and budget guards can query
"what did the agent spend today?".
"""

from __future__ import annotations

import fnmatch
import threading
import time
from datetime import date, timedelta
from typing import Any

# model pattern -> (input $/1M, output $/1M); first matching wins (ordered)
DEFAULT_PRICES: list[tuple[str, float, float]] = [
    ("glm-5.3*", 0.60, 2.20),
    ("glm-4*", 0.10, 0.10),
    ("gpt-4o*", 2.50, 10.00),
    ("gpt-4o-mini*", 0.15, 0.60),
    ("claude-*", 3.00, 15.00),
    ("nemotron*", 0.0, 0.0),      # local inference: electricity only
    ("llama3*", 0.0, 0.0),
    ("mock*", 0.0, 0.0),
    ("*", 0.50, 1.50),            # conservative default
]


def price_for(model: str,
              table: list[tuple[str, float, float]] | None = None) \
        -> tuple[float, float]:
    for pattern, price_in, price_out in (table or DEFAULT_PRICES):
        if fnmatch.fnmatchcase(model, pattern):
            return price_in, price_out
    return DEFAULT_PRICES[-1][1], DEFAULT_PRICES[-1][2]


class CostTracker:
    def __init__(self, prices: list[tuple[str, float, float]] | None = None):
        self._prices = prices or DEFAULT_PRICES
        self._lock = threading.Lock()
        self._by_model: dict[str, dict[str, float]] = {}
        self._by_tier: dict[str, dict[str, float]] = {}
        self._by_day: dict[str, float] = {}

    # ---------------------------------------------------------------- record
    def record(self, model: str, prompt_tokens: int, completion_tokens: int,
               tier: str = "unknown", cached: bool = False) -> dict:
        price_in, price_out = price_for(model, self._prices)
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        cost = (prompt_tokens * price_in + completion_tokens * price_out) / 1e6
        if cached:
            cost = 0.0
        today = date.today().isoformat()
        with self._lock:
            model_row = self._by_model.setdefault(
                model, {"calls": 0, "prompt_tokens": 0,
                        "completion_tokens": 0, "cost_usd": 0.0})
            model_row["calls"] += 1
            model_row["prompt_tokens"] += prompt_tokens
            model_row["completion_tokens"] += completion_tokens
            model_row["cost_usd"] += cost

            tier_row = self._by_tier.setdefault(
                tier, {"calls": 0, "cost_usd": 0.0})
            tier_row["calls"] += 1
            tier_row["cost_usd"] += cost

            self._by_day[today] = self._by_day.get(today, 0.0) + cost
        return {"model": model, "cost_usd": round(cost, 8),
                "price_per_mtok_in": price_in,
                "price_per_mtok_out": price_out}

    def estimate(self, model: str, prompt_tokens: int,
                 completion_tokens: int) -> float:
        price_in, price_out = price_for(model, self._prices)
        return round((prompt_tokens * price_in
                      + completion_tokens * price_out) / 1e6, 8)

    # ---------------------------------------------------------------- report
    def today_total(self) -> float:
        today = date.today().isoformat()
        with self._lock:
            return round(self._by_day.get(today, 0.0), 6)

    def recent_days(self, days: int = 7) -> dict[str, float]:
        """Per-day cost for the last ``days`` calendar days, oldest
        first; quiet days are present with 0.0 so charts need no
        gap-filling."""
        with self._lock:
            today = date.today()
            return {(today - timedelta(offset)).isoformat():
                    round(self._by_day.get(
                        (today - timedelta(offset)).isoformat(), 0.0), 6)
                    for offset in range(days - 1, -1, -1)}

    def total(self) -> float:
        with self._lock:
            return round(sum(self._by_day.values()), 6)

    def report(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_usd": round(sum(self._by_day.values()), 6),
                "by_day": dict(sorted(self._by_day.items())),
                "by_model": {model: {**row, "cost_usd":
                                     round(row["cost_usd"], 6)}
                             for model, row in self._by_model.items()},
                "by_tier": {tier: {**row, "cost_usd":
                                   round(row["cost_usd"], 6)}
                            for tier, row in self._by_tier.items()},
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }

    def within_budget(self, daily_budget_usd: float) -> bool:
        return self.today_total() <= daily_budget_usd
