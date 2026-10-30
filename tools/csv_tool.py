"""CSV parsing, filtering, sorting, and aggregation over in-memory text."""

from __future__ import annotations

import csv
import io
from typing import Any

_OPERATORS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: _num(a) > _num(b),
    "<": lambda a, b: _num(a) < _num(b),
    ">=": lambda a, b: _num(a) >= _num(b),
    "<=": lambda a, b: _num(a) <= _num(b),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
}


class CsvError(ValueError):
    pass


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CsvError(f"expected numeric value, got {value!r}") from exc


class Table:
    def __init__(self, rows: list[dict[str, str]]):
        self.rows = rows
        self.columns = list(rows[0].keys()) if rows else []

    @classmethod
    def parse(cls, text: str) -> "Table":
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(row) for row in reader]
        if not rows:
            raise CsvError("no data rows parsed")
        return cls(rows)

    # ------------------------------------------------------------------ ops
    def filter(self, column: str, op: str, value: str) -> "Table":
        if column not in self.columns:
            raise CsvError(f"unknown column {column!r}; have {self.columns}")
        if op not in _OPERATORS:
            raise CsvError(f"unknown operator {op!r}; have "
                           f"{sorted(_OPERATORS)}")
        predicate = _OPERATORS[op]
        return Table([row for row in self.rows
                      if column in row and predicate(row[column], value)])

    def sort(self, column: str, descending: bool = False) -> "Table":
        if column not in self.columns:
            raise CsvError(f"unknown column {column!r}")
        numeric = all(_maybe_num(row.get(column)) for row in self.rows)
        key = (lambda row: float(row[column])) if numeric else \
            (lambda row: str(row.get(column, "")))
        return Table(sorted(self.rows, key=key, reverse=descending))

    def aggregate(self, column: str) -> dict[str, Any]:
        if column not in self.columns:
            raise CsvError(f"unknown column {column!r}")
        values = [_num(row[column]) for row in self.rows
                  if _maybe_num(row.get(column))]
        if not values:
            raise CsvError(f"column {column!r} has no numeric values")
        return {"count": len(values), "sum": round(sum(values), 6),
                "avg": round(sum(values) / len(values), 6),
                "min": min(values), "max": max(values)}

    def group_aggregate(self, group_by: str, column: str) -> dict[str, dict]:
        if group_by not in self.columns or column not in self.columns:
            raise CsvError(f"columns must be in {self.columns}")
        groups: dict[str, list[float]] = {}
        for row in self.rows:
            if _maybe_num(row.get(column)):
                groups.setdefault(row[group_by], []).append(
                    float(row[column]))
        return {key: {"count": len(vals),
                      "sum": round(sum(vals), 6),
                      "avg": round(sum(vals) / len(vals), 6)}
                for key, vals in sorted(groups.items())}

    def head(self, n: int = 10) -> list[dict]:
        return self.rows[:n]

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"rows": len(self.rows),
                                "columns": self.columns}
        types = {}
        missing = {}
        distinct = {}
        for column in self.columns:
            values = [row.get(column, "") for row in self.rows]
            if all(v == "" for v in values):
                types[column] = "empty"
            elif all(_maybe_num(v) for v in values):
                types[column] = "number"
            else:
                types[column] = "text"
            missing[column] = sum(1 for v in values if v == "")
            distinct[column] = len({v for v in values if v != ""})
        info["column_types"] = types
        info["missing"] = missing
        info["distinct"] = distinct
        return info


def _maybe_num(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
