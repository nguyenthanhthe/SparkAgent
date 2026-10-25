# Testing guide

The suite is deliberately **offline and deterministic**: no network, no
LLM, no GPU, no sleeping (clocks are injected everywhere). That is why
567+ tests run in seconds and why they can gate every commit.

## Running

```
python -m unittest discover -s tests -t .          # everything
python -m unittest tests.test_security_wave -v     # one module
coverage run -m unittest discover -s tests -t .    # with coverage
coverage report --sort=cover
```

## Conventions

- **Plain `unittest`** — no pytest dependency; `IsolatedAsyncioTestCase`
  for async behavior.
- **Fakes over mocks** — `FakeBrain`, `FakeLocal/FakeRemote`,
  `FakePoster`, `FakeSession`, `RoleAwareBrain` implement the real
  interface with scripted replies; `mock.patch` is rare.
- **Injectable clocks** — token buckets, TTL caches, approval expiry,
  circuit cooldowns all use `FakeClock.advance`, never `sleep`.
- **Temp directories** — every store test builds its own
  `tempfile.TemporaryDirectory`; nothing touches `data/`.
- **Failure paths required** — a test suite that only checks happy
  paths proves nothing; nearly every module has explicit
  tamper/blocked/rejected cases (the git history is full of real bugs
  these caught).

## Testing a new component

1. Happy path(s).
2. Every validation/error branch — assert the *message content*, not
   just the exception type (messages become model observations).
3. Boundary behavior (empty input, overflow, expired, unauthorized).
4. If the component is async: cancellation and timeout behavior via
   `IsolatedAsyncioTestCase`.

## Speed discipline

The full suite should stay well under ~90 seconds on a laptop. If a test
needs real waiting, it is testing the wrong thing — inject a clock. The
one CPU-bound area (skill smoke timeouts) uses short, terminating loops
by design.

## Self-check

`python main.py --check` runs an offline smoke of the composed system
(config, policy, SSRF guard, vault crypto, memory recall, ReAct parsing)
— a fast post-install sanity probe, separate from the unit suite.

## Patterns introduced in Waves R–S

**Dependency tests** (`tests/test_task_dependencies.py`) build a bare
`Memory` over a temp database, submit tasks with `depends_on`, and step
through the state machine (`mark_task_running` → `finish_task`) to prove
the gate: a dependent task stays out of `due_tasks` until every
dependency settles to `done`. Corrupt `depends_on` JSON must degrade to
"no dependencies", not block forever — there is a test for that.

**Topology tests** (`tests/test_topology_render.py`) assert the catalog
is complete and that `docs/topologies.md` matches
`swarm.render.markdown_section()` byte-for-byte — generated docs get the
same staleness treatment as `docs/configuration.md`.

**Security-tool tests** (`tests/test_sqlite_query_tool.py`) prove the
guard structurally: the statement text is a fixed constant per table, so
the test asserts the API contract (unknown table/column rejected, row
caps clamped) and that a `mode=ro` connection refuses writes even if a
write slipped past the API.

**Web endpoint tests** use the `TestClient`/`TestServer` pair against
`build_web_app(daemon)` with a temp-database `AgentDaemon` — no network,
no daemon thread. Copy `tests/test_memories_filters.py` for query-parameter
endpoints and `tests/test_quarantine_restore.py` for multi-step flows.
