# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[125/500]** commits · **621 tests green** after every wave.

## Wave L status

1. ✅ cron daily_at spec — multiple times + weekday filters (105)
2. ✅ swarm progress events on the bus (106)
3. ✅ tool latency metrics in registry.call (100)
4. ✅ episode consolidation into digest memories (104)
5. ✅ /api/audit redacted + paginated, /api/version (103)
6. ⬜ brain router status endpoint aggregation
7. ✅ /api/version (103)
8. ✅ testing guide (107)
9. ✅ approvals workflow example (108)
10. ✅ signed skills: persist + verify-or-refuse + vault wiring (101, 102)

## Wave K status (complete)

Episode detail (89) · budget guard (90) · smoke tests (91) · exec rate
limits (92, 93) · graph tools (94, 95) · telegram /health (96) ·
pagination (97) · CI coverage (98).

## Wave M status

1. ✅ /api/brain — tier health, stats, cost ledger, budget (110)
2. ⬜ dashboard cost/brain panels
3. ⬜ task retries with backoff
4. ✅ openshell dry-run policy probe (111)
5. ✅ memory kind-filtered recall (112)
6. ✅ /ws websocket with redacted log forwarding (116)
7. ✅ swarm per-run role-call budget (113)
8. ✅ approval-expiry sweep with notifications (117)
9. ✅ generated config reference + staleness test (114)
10. ✅ graph build-from-text example (118)

## Wave N status

1. ✅ dashboard spend panel wired to /api/brain (122)
2. ✅ task retries with exponential backoff (121)
3. ✅ react adaptive context budgeting (120)
4. ⬜ response cache wired into Brain.chat
5. ✅ telegram /audit (123)
6. ⬜ per-program working-directory allowlist
7. ⬜ swarm debate progress on /ws
8. ⬜ visible promptguard scores in observations
9. ⬜ mermaid architecture diagrams
10. ✅ cron walkthrough example (124)

## Wave O backlog (next)

1. response cache + router stats inside Brain.bridge (adapter upgrade)
2. openshell per-program cwd allowlist
3. swarm debate progress over /ws
4. promptguard score surfaced in web_fetch tool results
5. docs: mermaid diagrams for architecture + data flow
6. kernel: spawn a periodic 'nightly digest' scheduled task by default
7. interface: /api/tools endpoint listing tool specs
8. security: rate-limit login attempts on /api when token set
9. tests: golden-file prompts for the ReAct system contract
10. ops: log rotation config + data/ disk quota check

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
