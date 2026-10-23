# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[98/500]** commits · **567 tests, all green**.

## Wave K status

1. ✅ `GET /api/episodes/{id}` episode detail with step replay (89)
2. ⬜ cron-style daily_at list + weekday filter
3. ✅ daily budget guard wired into brain (90)
4. ✅ skillforge smoke tests before activation (91)
5. ✅ pagination envelopes on tasks/episodes (97)
6. ⬜ debate rounds streamed to bus
7. ✅ telegram /health (96)
8. ✅ graph extraction tools + daemon persistence (94, 95)
9. ✅ per-program exec rate limits (92, 93)
10. ✅ CI coverage (98)

## Wave L backlog (next)

1. kernel/scheduler cron weekday filter + multiple daily_at times
2. swarm debate/consensus progress events on the bus (live dashboard feed)
3. metrics wiring: tool latency histogram in registry.call
4. memory consolidation job using summarizer (housekeeping extension)
5. openshell: command audit trail API endpoint (recent audit rows)
6. brain: adapter health endpoint aggregated from router.status
7. interface: /api/version endpoint + build info
8. docs: testing guide + troubleshooting expansion
9. examples: cron + approvals workflow example
10. security: signed skill header verification on load (wire signatures into skillforge)

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
| K | Subsystem v2s (episode detail, budget guard, smoke tests, rate limits, graph tools, pagination) | done |

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
