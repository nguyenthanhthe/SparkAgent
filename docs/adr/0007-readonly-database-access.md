# ADR-0007: Read-only database access pattern

Status: accepted

## Context

Agents benefit from inspecting their own history (episodes, tasks,
audit rows), and the `sqlite_query` tool plus the `/api/db` endpoint
give them that. But any code path that turns user input into SQL text
is an injection surface by construction, and heuristic validators
("does the query contain SELECT?") are bypassable by tokenizing tricks.
The tool also lives on a path an LLM drives — the input is adversary-
adjacent by definition.

## Decision

Database lookups exposed to the agent use *static statements only*: one
fixed `SELECT * FROM <table> ORDER BY id DESC LIMIT ?` string constant
per whitelisted table, with the row cap bound as a parameter. All
shaping happens client-side in Python on the fetched rows — projection,
equality filtering, ordering, and the final limit. The connection opens
with `mode=ro` so SQLite itself rejects writes even if a caller
misuses the API. Both the ReAct tool (`tools/sqlite_query.py`) and the
HTTP endpoint (`/api/db/{table}`) route through the same `lookup()`
function, so there is exactly one guarded path.

## Consequences

- No user input ever becomes part of a SQL statement — there is
  nothing to parameterize because there is nothing to interpolate.
- Lookups scan at most `FETCH_CAP` (500) recent rows and filter
  client-side. This is the right trade-off for an agent inspecting its
  own recent history, and the response says `scanned` honestly so
  callers know the scope.
- Write access stays exclusively in `kernel/memory.py` methods, which
  use fixed statements with bound parameters.
- Row and cell-size caps bound response size; the row cap clamps
  rather than errors (agent-friendly), while the connection's
  read-only mode is the hard backstop.

## Alternatives

- **Free-form read-only SQL with keyword filters** — rejected:
  allowlisting is the pattern's whole point; keyword checks degrade
  into a denial game with no principled end.
- **Parameterized dynamic SQL (identifiers whitelisted by regex)** —
  safer than raw strings but still builds statement text from input;
  a static-statement design achieves the same feature set with a
  strictly smaller surface.
- **A separate reporting database replica** — deferred: on a single
  personal machine, `mode=ro` plus static statements is sufficient;
  a replica adds sync complexity for no additional guarantee the
  threat model needs.
