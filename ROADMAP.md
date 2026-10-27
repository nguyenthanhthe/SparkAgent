# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[211/500]** commits · **906 tests green** · self-check passing.

## Wave S status (complete)

1. ✅ interface: task detail exposes `blocked_by` (unsatisfied dependency ids)
2. ✅ interface: dashboard swarm-topology cards fed from /api/swarm
3. ✅ brain: /api/adapters tier stats with last_error + cooldown remaining
4. ✅ interface: /api/memories combined kind+tag filters; Brain.embed degrades on any transport failure
5. ✅ security: quarantine restore-with-approval (two-step audited release)
6. ✅ openshell: per-program wall-clock budget veto at the admission gate (`openshell.program_timeouts`)
7. ✅ interface: /api/db read-only lookups + CLI `sqlite` command over the tool's guarded path
8. ✅ ops: combined preflight CLI (config + brain + disk, severity exit codes)
9. ✅ docs: testing guide — dependency/topology/security-tool patterns
10. ✅ examples: dependency chain demo (blocked → released)

## Wave T status (complete)

1. ✅ kernel: scheduler blocked/released events on the `scheduler` channel, streamed over /ws and SSE
2. ✅ brain: per-entry cache hit counts; /api/brain `cache_top_hits` (key digests, never prompts)
3. ✅ memory: consolidation carries episode tags into digest memories (hashtags + meta)
4. ✅ security: promptguard score histogram (`promptguard_score`) in the metrics registry
5. ✅ interface: dashboard task drawer — blocked_by, priority, dependencies inline
6. ✅ openshell: time-budget veto counter (`exec_timebudget_blocked_total`)
7. ✅ tools: json_query wildcard dot-paths (`items.*.name`, nested, spread semantics)
8. ✅ ops: backup `verify-all` — whole retention window verified in one command
9. ✅ docs: ADR-0007 — read-only database access via static statements
10. ✅ examples: sqlite_query drill-down demo (tasks → audit)

## Wave U status (complete)

1. ✅ openshell: rate-limit veto counter (`exec_ratelimit_blocked_total`) beside the budget counter
2. ✅ brain: streamed chats record cost/usage even when abandoned or cut mid-flight
3. ✅ memory: consolidation seeds the entity graph from digest texts (`source=consolidation`)
4. ✅ security: /api/db pinned through the auth limiter when SPARKAGENT_WEB_TOKEN is set
5. ✅ interface: telegram `/db` command for read-only lookups from chat
6. ✅ interface: dashboard scheduler panel shows blocked-task count (`scheduler.stats.blocked_tasks`)
7. ✅ tools: web_fetch conditional GET (ETag/If-None-Match) with 304 short-circuit
8. ✅ ops: backup manifest gains an optional `--tag` label surfaced in verify output
9. ✅ docs: runbook — dependency chains (blocked tasks, manual release, failure semantics)
10. ✅ examples: backup create/verify/restore drill demo

## Wave V status (complete)

1. ✅ kernel: submit-time dependency guard — transitive closure walk rejects cycles and dangling ids
2. ✅ brain: /api/brain gains a gap-free 7-day cost breakdown (`costs_last_7_days`)
3. ✅ memory: recall snippets — matched query terms highlighted (`memory_search/snippets.py`)
4. ✅ security: quarantine listing filter by reason substring (`/api/quarantine?reason=`)
5. ✅ interface: telegram `/blocked` command listing dependency-stalled tasks
6. ✅ interface: dashboard cost panel shows today vs 7-day average
7. ✅ tools: json_query mode=filter — numeric/string comparison terms over list rows
8. ✅ ops: backup `drill` subcommand — verify + restore into a scratch dir, never the live one
9. ✅ docs: ADR-0008 — conditional fetch and cache semantics for web tools
10. ✅ examples: web_fetch 304 drill demo (local server, two rounds)

## Wave W backlog (next)

1. kernel: scheduler concurrency metric (`scheduler_inflight` gauge) exposed via /api/metrics
2. brain: adapter registry gains a ping probe (per-adapter latency sample in /api/adapters)
3. memory: digest dedupe — consolidation skips episodes whose goal text already appears in a digest
4. security: auth limiter exposes lockout state in /api/status (count + retry-after, no client detail)
5. interface: telegram `/skills` shows pending-approval skills with hint to use /approve
6. interface: dashboard backup panel fed from /api/backup status (last archive, age, tag)
7. tools: json_query mode=sort — order list rows by a key, ascending/descending
8. ops: diskwatch gains a `--json` output mode for machine-readable checks
9. docs: runbook — backup drills (create, tag, verify-all, drill, restore-for-real)
10. examples: json_query filter+sort drill demo over task rows

## Wave R status (complete)

1. ✅ kernel: task dependencies (`depends_on`) gate `due_tasks` until deps done (ADR-0006)
2. ✅ interface: `/api/metrics` JSON snapshot with uptime
3. ✅ memory: graph-boosted recall (`memory_search/graph_boost.py`, wired via `memory.graph_store`)
4. ✅ swarm: topology catalog with mermaid diagrams at `/api/swarm` + `swarm/render.py`
5. ✅ ops: diskwatch CLI (`python -m ops.diskwatch`, severity exit codes)
6. ✅ interface: Prometheus rendering extracted to `interface/prom.py`
7. ✅ brain: preflight CLI (`python -m brain.preflight`, per-tier health gate)
8. ✅ tools: `sqlite_query` — read-only agent-database lookups, static statements
9. ✅ docs: ADR-0006 + generated topology catalog page (`docs/topologies.md`)
10. ✅ examples: `topology_demo.py` — all five composition shapes offline

## Wave S status (complete)


## Wave L status

1. ✅ cron daily_at spec — multiple times + weekday filters (105)
2. ✅ swarm progress events on the bus (106)
3. ✅ tool latency metrics in registry.call (100)
4. ✅ episode consolidation into digest memories (104)
5. ✅ /api/audit redacted + paginated, /api/version (103)
6. ✅ brain router status endpoint aggregation (/api/adapters: tier health + cache + adapter catalog)
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
2. ✅ dashboard cost/brain panels
3. ✅ task retries with backoff
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
4. ✅ response cache wired into Brain.chat (since 129, stats exposed)
5. ✅ telegram /audit (123)
6. ✅ per-program working-directory allowlist
7. ✅ swarm debate progress on /ws
8. ✅ visible promptguard scores in observations (injection_risk in web_fetch results, since 41)
9. ✅ mermaid architecture diagrams
10. ✅ cron walkthrough example (124)

## Wave O status

1. ✅ response cache + router stats inside Brain.bridge (cache snapshot in /api/brain + spend panel)
2. ✅ openshell per-program cwd allowlist
3. ✅ swarm debate progress over /ws
4. ✅ promptguard report already in web_fetch results (since 41)
5. ✅ mermaid diagrams (129)
6. ✅ seeded nightly digest task (128)
7. ✅ /api/tools manifest (126)
8. ✅ token-auth rate limiting (security.auth_limiter, 429 with Retry-After)
9. ✅ golden prompt contract tests (127)
10. ✅ disk quota watch in housekeeping (130)

## Wave Q status (complete)

1. ✅ brain: streaming chat through the bridge (chat_stream, failover before first chunk)
2. ✅ interface: dashboard swarm activity feed via SSE swarm events
3. ✅ openshell: per-program exec latency histograms (exec_seconds_<program>)
4. ✅ kernel: episode tags enrich memory recall hits + /api/memories
5. ✅ security: quarantine TTL auto-expiry sweep (housekeeping, security.quarantine.ttl_seconds)
6. ✅ tools: json_query JSONL mode (line-numbered parse errors)
7. ✅ docs: GPU tier failover runbook (docs/runbook-failover.md)
8. ✅ brain: per-role temperature via swarm.temperature.<role>, wired through Brain.chat
9. ✅ interface: /api/tasks/{id} detail endpoint
10. ✅ ops: backup CLI (python -m ops.backup) with skills dir + retention pruning

## Wave P status (complete)

1. ✅ Brain.bridge cost recording on every chat (client-reported usage, cache hits recorded as free calls)
2. ✅ openshell: per-program working-directory allowlist (ADR-0004)
3. ✅ swarm: debate/consensus progress events on the swarm channel, forwarded over /ws
4. ✅ security: auth-attempt rate limiting when SPARKAGENT_WEB_TOKEN set
5. ✅ kernel: episode tagging + tag-filtered history (since 144)
6. ✅ brain: streaming chat adapter option (SSE transport, single-chunk fallback)
7. ✅ interface: dashboard episodes list + episode-detail viewer page
8. ✅ tools: file_ops tool (read/list/write/stat via registry, policy-confined)
9. ✅ docs: ADR (architecture decision records) index
10. ✅ ops: systemd unit for Linux parity with NSSM docs

## Wave P backlog (next)

1. Brain.bridge: response cache + cost recording on every chat (wire existing cache/costs)
2. openshell: per-program working-directory allowlist
3. swarm: debate/consensus progress over /ws (agent-visible)
4. security: auth-attempt rate limiting when SPARKAGENT_WEB_TOKEN set
5. kernel: episode tagging + tag-filtered history
6. brain: streaming chat adapter option
7. interface: dashboard episode-detail viewer page
8. tools: file_ops skill tool (read/list in sandbox via registry, not just helpers)
9. docs: ADR (architecture decision records) index
10. ops: systemd unit for Linux parity with NSSM docs

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
