# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[87/500]** commits toward the 500-commit target.

## Waves

| Wave | Theme | Status |
|---|---|---|
| A | Kernel core utilities (errors, async, clock, limits, retry, circuit breaker, metrics, health, correlation, validation) | done |
| B | Security hardening (policy engine, approvals, prompt guard, signatures, quarantine, profiles, process registry, env guard) | done |
| C | Brain adapters (mock/ollama/openai_compat), response cache, cost tracking, context budgeting, tier router | done |
| D | Tool library (calculate, text/json/csv/stats, memory tools, ask_human) + webfetch prompt-guard | done |
| E | Multi-agent swarm (mailbox, blackboard, orchestrator, consensus, critic, topologies, delegate tools) | done |
| F | Memory evolution (BM25, hybrid RRF recall, graph store, summarizer) | done |
| G | Interface v3 (OpenAPI, CLI, dashboard approvals+quarantine panels) | done |
| H | Ops (pyproject, backup/restore, Docker, JSON logging, benchmarks) | done |
| I | Docs (10 pages) + examples (5 runnable) | done |
| J | Kernel utilities v2 (serialization, pagination, expiring cache) | done |
| K | Subsystem v2s — NEXT |

## Wave K backlog (next up)

1. `GET /api/episodes/{id}` — full episode detail (steps replay) + test
2. kernel/scheduler: cron-style `daily_at` list + `weekday filter`
3. brain: daily budget guard wired into router (CostTracker.within_budget veto)
4. skillforge: optional smoke-test execution before activation (sandbox call with dummy args)
5. web: use pagination envelope on /api/tasks and /api/episodes
6. swarm: debate rounds streamed to bus for live dashboard view
7. telegram: /health mapping to health registry
8. memory: graph extraction tool (triples from text heuristics)
9. openshell: per-program rate limits via RateLimiterSet
10. CI: coverage upload + badge

## Conventions (keep following)

- one component = one commit (`feat(scope): ... [n/500]`), push every commit
- `set -o pipefail; python -m compileall -q <pkgs> && python -m unittest <target tests> -q` before each commit
- full suite after each wave; ROADMAP update commit at milestones
- no SQL string building; no credentials; deny-by-default network/process code

Rules: every commit keeps `python -m unittest discover -s tests -t .` green.
