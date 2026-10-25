"""sqlite_query — read-only lookups over the agent database.

Lets the ReAct core inspect episodes, steps, memories, tasks, and audit
rows. Safety is structural: the statement text is a fixed constant per
table (only the row cap is bound as a parameter), the connection opens
with ``mode=ro`` so SQLite itself rejects writes, and filtering,
projection, ordering, and the final limit are applied in Python on the
fetched rows. No user input ever becomes part of a SQL string.

Because filtering happens client-side, each lookup reads at most
FETCH_CAP recent rows (id DESC) and matches against those — the right
trade-off for an agent inspecting its own recent history.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from kernel.errors import ToolFailure
from tools.registry import Tool, ToolContext, ToolRegistry

FETCH_CAP = 500
MAX_ROWS = 100
DEFAULT_ROWS = 20
MAX_CELL_CHARS = 2000
MAX_WHERE_TERMS = 4
_TABLES = ("episodes", "steps", "memories", "tasks", "audit")

# Static statement per table — the only variable part is the bound LIMIT.
_STATEMENTS = {table: "SELECT * FROM " + table
               + " ORDER BY id DESC LIMIT ?" for table in _TABLES}


def _trim_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value if not isinstance(value, str)
            or len(value) <= MAX_CELL_CHARS
            else value[:MAX_CELL_CHARS] + "…"
            for key, value in row.items()}


def _run(db_path: Path, table: str,
         cap: int) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                 timeout=5.0)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(_STATEMENTS[table],
                                  (cap,)).fetchall()
    except sqlite3.Error as exc:
        raise ToolFailure(f"query failed: {exc}") from exc
    finally:
        connection.close()
    return [_trim_row(dict(row)) for row in rows]


async def lookup(db_path: Path, table: str,
                 columns: list[str] | None = None,
                 where: dict[str, Any] | None = None,
                 order_by: str | None = None,
                 descending: bool = False,
                 limit: int = DEFAULT_ROWS) -> dict[str, Any]:
    """Shared read-only lookup — the tool handler and the /api/db endpoint
    both go through this one guarded path."""
    if table not in _TABLES:
        raise ToolFailure(f"unknown table {table!r} — one of "
                          + ", ".join(_TABLES))
    if where and len(where) > MAX_WHERE_TERMS:
        raise ToolFailure(f"at most {MAX_WHERE_TERMS} where terms")
    limit = max(1, min(int(limit), MAX_ROWS))
    rows = await asyncio.to_thread(_run, db_path, table, FETCH_CAP)

    for column, value in (where or {}).items():
        rows = [row for row in rows if row.get(column) == value]
    if order_by is not None:
        rows.sort(key=lambda row: (row.get(order_by) is None,
                                   row.get(order_by)),
                  reverse=descending)
    elif descending:
        rows.reverse()
    if columns:
        missing = [c for c in columns
                   if rows and c not in rows[0]]
        if missing:
            raise ToolFailure(f"unknown column(s): {missing}")
        rows = [{c: row.get(c) for c in columns} for row in rows]
    rows = rows[:limit]
    return {"rows": rows, "count": len(rows), "table": table,
            "scanned": FETCH_CAP}


def register_tools(registry: ToolRegistry, db_path: Path) -> None:
    async def sqlite_query(ctx: ToolContext, table: str,
                           columns: list[str] | None = None,
                           where: dict[str, Any] | None = None,
                           order_by: str | None = None,
                           descending: bool = False,
                           limit: int = DEFAULT_ROWS) -> dict[str, Any]:
        return await lookup(db_path, table, columns=columns, where=where,
                            order_by=order_by, descending=descending,
                            limit=limit)

    registry.register(Tool(
        name="sqlite_query",
        description=("Read-only lookup on the agent database. table: "
                     "episodes|steps|memories|tasks|audit (most recent "
                     "500 rows scanned); optional columns projection, "
                     "where (up to 4 equality terms), order_by with "
                     "descending flag, limit (max 100). Writes are "
                     "impossible — the database opens read-only."),
        parameters={
            "table": {"type": "string", "required": True},
            "columns": {"type": "array", "required": False},
            "where": {"type": "object", "required": False},
            "order_by": {"type": "string", "required": False},
            "descending": {"type": "boolean", "required": False},
            "limit": {"type": "integer", "required": False},
        },
        handler=sqlite_query))
