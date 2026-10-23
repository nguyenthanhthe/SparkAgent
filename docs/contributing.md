# Contributing

## Ground rules

1. **Tests stay green.** `python -m unittest discover -s tests -t .`
   must pass before every commit — no exceptions, no skips added to make
   it pass.
2. **Atomic commits.** One component (module + its tests) per commit,
   `feat(scope): summary` style. If you need two commits to explain the
   change, it is two changes.
3. **No credentials in the tree.** Environment or vault only. Examples
   and tests use placeholders that could never authenticate.
4. **Parameter-bound SQL only.** No f-strings, `.format`, or `%` building
   statements — column names are code constants, values are `?`.
5. **Deny-by-default.** New network code validates scheme/host/port and
   rejects private/loopback/link-local targets. New process code goes
   through OpenShell.

## Layout

`kernel/` runtime · `openshell/`+`security/` execution & trust ·
`brain/` LLM tiers · `tools/`+`swarm/` capabilities · `interface/` humans
· `memory_search/` retrieval · `ops/` service tooling · `docs/` ·
`examples/` · `tests/` (pure unittest, no network, no LLM).

## Adding a component

1. Write the module with a docstring stating its contract.
2. Write `tests/test_<module>.py` — include failure paths, not just happy
   ones (the suite's history is full of bugs caught that way).
3. `python -m compileall -q . && python -m unittest discover -s tests -t .`
4. Commit: `feat(<scope>): <what> [n/500]` and push.

## Adding an LLM provider

Implement `brain.adapters.base.ChatAdapter`, register a factory in the
adapter registry, and add a config section. The router, cache, and cost
tracking pick it up with zero changes elsewhere.

## Benchmarks

`python -m benchmarks.bench --quick` before and after performance-
sensitive changes; keep numbers in the same order of magnitude.
