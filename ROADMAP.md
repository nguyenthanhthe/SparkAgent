# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[491/500]** commits · **1115 tests green** · self-check passing.

## Wave AO status (complete)

1. ✅ kernel: submit distinguishes whitespace-only goals from empty ones in the rejection
2. ✅ brain: cache snapshot reports the average entry age
3. ✅ memory: recall created_after validates its format with a clear error
4. ✅ security: quarantine records carry a source label (web_fetch stamps itself)
5. ✅ interface: dashboard skills panel shows the source column
6. ✅ interface: telegram /skills pending block announces its count
7. ✅ tools: csv_analyze describe reports per-column distinct counts
8. ✅ ops: backup prune --dry-run reports what would remain
9. ✅ docs: runbook-backups cross-links the FAQ unverified entry
10. ✅ examples: approval counters demo — queue lifecycle offline

## Wave AP status (complete)

1. ✅ kernel: task_finished event carries the episode step count
2. ✅ brain: adapter registry keeps the last 5 probe failures; /api/brain lists them
3. ✅ memory: rename_key refuses an existing target key (no silent merge)
4. ✅ security: request_to_dict carries decided_at (observers already fired on expiry — stale item substituted)
5. ✅ interface: dashboard uptime line shows the agent version
6. ✅ interface: telegram /tasks accepts a validated --status filter
7. ✅ tools: json_query mode=keys honors a case-insensitive prefix filter
8. ✅ ops: create --verify-immediately fails with JSON ok=false instead of a traceback
9. ✅ docs: architecture capability table gains the event bus row
10. ✅ examples: diskwatch demo — level + subdirectory breakdown offline

## Wave AQ status (complete)

1. ✅ kernel: pause/resume events carry the task source
2. ✅ brain: cache snapshot splits hit share per model
3. ✅ memory: forget() raises on an empty key, distinct from an absent one
4. ✅ security: quarantine release audit carries the quarantine reason
5. ✅ interface: adapters card shows the per-adapter probe failure ledger
6. ✅ interface: telegram /backup --tag filter narrows the listing
7. ✅ tools: json_query filter gains a $= ends-with operator
8. ✅ ops: verify-all summaries carry a checked_at stamp
9. ✅ docs: ADR-0012 — quarantine source labels and release auditing
10. ✅ examples: keys demo — json_query mode=keys + prefix offline

## Wave AR status (complete)

1. ✅ kernel: task.submit audit line mirrors the trimmed goal
2. ✅ brain: /api/brain adapters section stamps checked_at
3. ✅ memory: recall honors an explicit ids filter (parameter-bound IN list)
4. ✅ security: quarantine expire() audits the sweep count on the audit bus
5. ✅ interface: dashboard episode table shows the step count column
6. ✅ interface: telegram /mem accepts an --after date filter (validated)
7. ✅ tools: json_query mode=stats reports per-key leaf counts
8. ✅ ops: backup create lands its file count in the daemon audit trail
9. ✅ docs: faq.md entry — why quarantine records carry a source label
10. ✅ examples: filter demo — the full where-term grammar offline

## Wave AS status (complete)

1. ✅ kernel: task_finished carries the retry_backoff_s when a transient failure requeues
2. ✅ brain: tier_details stamps last_success_at per tier
3. ✅ memory: recall snippet honors a caller-supplied highlight needle
4. ✅ security: quarantine put() rejects a whitespace-only reason
5. ✅ interface: task drawer renders cancelled as an error badge
6. ✅ interface: telegram /db usage hint lists live per-table row counts
7. ✅ tools: csv aggregate errors name the numeric columns
8. ✅ ops: backup drill lands its outcome in the audit trail via --data-dir
9. ✅ docs: api.md documents POST /api/memories/rename
10. ✅ examples: retry demo — backoff schedule + recovery walkthrough offline

## Wave AT status (complete)

1. ✅ kernel: task.submit audit carries the depends_on ids
2. ✅ brain: /api/brain lifecycle carries the bus overflow counter
3. ✅ memory: recall exposes last_recall_pool_size for tuning
4. ✅ security: quarantine stats breaks item counts down by source
5. ✅ interface: cost panel shows tokens saved per model
6. ✅ interface: telegram /skills accepts a status= filter
7. ✅ tools: json_query mode=search reports the match count
8. ✅ ops: backup prune audits actual removals via --data-dir
9. ✅ docs: configuration.md explains the daily budget veto (via the generator)
10. ✅ examples: stats demo — leaves_by_key rendered offline

## Wave AU status (complete)

1. ✅ kernel: task_finished events carry the agent's model tier
2. ✅ brain: cache snapshot reports the oldest-hit age
3. ✅ memory: recall honors explicit k=0 as a candidate-pool probe
4. ✅ security: quarantine get() exposes the record age in human form
5. ✅ interface: task drawer shows the task source (no episode-task-id link exists — stale item substituted)
6. ✅ interface: telegram /audit accepts an --action filter
7. ✅ tools: json_query wildcard paths honor slice ranges
8. ✅ ops: diskwatch warn level names the prune target
9. ✅ docs: faq.md entry — what the bus overflow counter means
10. ✅ examples: quarantine demo — source breakdown offline

## Wave AV backlog (next)

1. kernel: task_started event carries the task priority
2. brain: /api/adapters pings carry a checked_at per probe
3. memory: recall snippet honors a width of 0 (no snippet work at all)
4. security: approval request_to_dict carries the requested summary kind
5. interface: dashboard skills pending badge shows the pending count
6. interface: telegram /blocked gains an --all flag beyond the limit
7. tools: csv_analyze filter validates the op before the column
8. ops: backup verify prints the archive byte size
9. docs: testing.md documents the gated-commit chain verbatim
10. examples: wildcard demo — slice ranges + spread offline

1. kernel: task_finished events carry the agent's model tier
2. brain: cache snapshot gains an oldest-hit age (how stale can a served answer be)
3. memory: recall honors an explicit k=0 (returns only the pool size)
4. security: quarantine get() exposes record age in human form
5. interface: dashboard episodes panel links the task it came from
6. interface: telegram /audit gains a --action filter
7. tools: json_query wildcard paths honor a slice range
8. ops: diskwatch --json carries the threshold pair it evaluated against
9. docs: faq.md entry — what the bus overflow counter means
10. examples: quarantine demo — source breakdown rendered offline

1. kernel: task submit audits the depends_on ids alongside the goal
2. brain: /api/brain lifecycle carries the bus overflow counter
3. memory: recall exposes its candidate-pool size for tuning
4. security: quarantine stats gains a source breakdown
5. interface: dashboard cost panel shows the saved tokens per model
6. interface: telegram /skills filter matches on status too (status=x)
7. tools: json_query mode=search reports the match count alongside
8. ops: backup prune audits what it removed via --data-dir
9. docs: configuration.md documents the brain.daily_budget_usd surface
10. examples: stats demo — json leaves_by_key rendered offline

1. kernel: task retry backoff is visible in the task_finished event
2. brain: tier_details gains a last_success_at stamp
3. memory: recall snippet honors a caller-supplied highlight needle
4. security: quarantine put() rejects a whitespace-only reason too
5. interface: dashboard task drawer shows the cancelled state distinctly
6. interface: telegram /db tables hint lists the row counts
7. tools: csv_analyze sort validates the column exists with a clear error
8. ops: backup drill --keep protects the scratch dir from retention
9. docs: api.md documents the /api/memories/rename endpoint
10. examples: retry demo — backoff schedule rendered offline

1. kernel: submit() audits with the trimmed goal, not the raw input
2. brain: /api/brain adapters section gains a checked_at stamp
3. memory: recall honors an explicit ids filter for direct lookups
4. security: quarantine expire() audits what it swept (counts per run)
5. interface: dashboard episode table shows the step count column
6. interface: telegram /mem accepts an --after date filter
7. tools: json_query mode=stats gains a per-key leaf count
8. ops: backup create logs its file count into the daemon audit trail
9. docs: faq.md entry — why quarantine records carry a source label
10. examples: filter demo — the full where-term grammar offline

1. kernel: task pause/resume events carry the task source
2. brain: cache snapshot gains a hit-rate-per-model split
3. memory: forget() on a missing key distinguishes from a forgotten empty key
4. security: quarantine release() returns the record's reason for the audit trail
5. interface: dashboard adapters card shows the probe failure ledger
6. interface: telegram /backup --tag filter narrows the listing
7. tools: json_query mode=filter gains a case-insensitive =~ variant
8. ops: backup verify-all prints a per-archive timing line in verbose mode
9. docs: ADR-0012 — quarantine source labels and release auditing
10. examples: keys demo — json_query keys+prefix offline walkthrough

1. kernel: task_finished event carries the episode step count
2. brain: /api/brain adapters section lists recent probe failures per adapter
3. memory: rename_key rejects renaming to a key that already exists
4. security: approval observers fire on expiry transitions too
5. interface: dashboard uptime line shows the agent version
6. interface: telegram /tasks accepts a --status filter
7. tools: json_query mode=keys honors a prefix filter
8. ops: backup create --verify-immediately prints the verify outcome in its JSON
9. docs: architecture.md capability table gains the bus overflow counter
10. examples: subdirs demo — diskwatch breakdown rendered offline

1. kernel: task submit rejects a goal that is only whitespace (echoing the skip)
2. brain: cache snapshot gains an average entry age
3. memory: recall created_after validates its format with a clear error
4. security: quarantine put() carries a source label in meta
5. interface: dashboard skills panel shows the source column
6. interface: telegram /skills pending block shows the count
7. tools: csv_analyze describe gains a per-column distinct count
8. ops: backup prune --dry-run reports what would remain
9. docs: runbook-backups.md cross-links the FAQ unverified entry
10. examples: counters demo — approval queue lifecycle offline

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

## Wave W status (complete)

1. ✅ kernel: scheduler inflight/blocked gauges (`scheduler_inflight`, `scheduler_blocked`) in /metrics + /api/metrics
2. ✅ brain: adapter ping probe — per-adapter latency samples in /api/adapters
3. ✅ memory: digest dedupe — consolidation skips goals already distilled
4. ✅ security: auth limiter aggregate lockout state exposed via /api/status
5. ✅ interface: telegram `/skills` — pending-approval skills grouped first with /approve hint
6. ✅ interface: dashboard backup panel fed from /api/backup (newest, age, tag)
7. ✅ tools: json_query mode=sort — order list rows by a key, missing keys always last
8. ✅ ops: diskwatch `--json` (already implemented + tested when queued — verified, no change needed)
9. ✅ docs: runbook — backup drills (create, tag, verify-all, scratch restore)
10. ✅ examples: json_query filter+sort drill demo over task rows

## Wave X status (complete)

1. ✅ kernel: shutdown drain counter — `shutdown_drained_tasks` when inflight episodes finish on stop
2. ✅ brain: response cache hits broken down by model (`hits_by_model` in snapshot)
3. ✅ interface: telegram `/mem` gains a `--kind` filter passed to recall
4. ✅ security: promptguard verdict counters (pass/sanitize/quarantine) in the metrics registry
5. ✅ interface: dashboard adapters card renders the ping latency samples
6. ✅ interface: telegram `/backup` command over a shared `list_backups` helper (chat, web, dashboard)
7. ✅ tools: json_query mode=first/last — head/tail row access with optional filter
8. ✅ ops: backup `verify-all --json` (already JSON-native when queued — verified, no change needed)
9. ✅ docs: ADR-0009 — digest dedupe and consolidation idempotency
10. ✅ examples: backup end-to-end demo (create → list → verify window → drill → tamper)

## Wave Y status (complete)

1. ✅ kernel: task pause/resume emits `task_paused`/`task_resumed` on the scheduler channel
2. ✅ brain: /api/brain exposes `shutdown_drained_tasks` in a lifecycle block
3. ✅ memory: `Memory.forget(key)` + audited `DELETE /api/memories/{key}`
4. ✅ security: quarantine meta carries the source URL for webfetch quarantines (already in place — verified)
5. ✅ interface: telegram `/skills` truncates at 20 entries with a more-hint
6. ✅ interface: dashboard adapters card shows per-tier cooldown (breaker) state
7. ✅ tools: json_query mode=group — counts per key value, optional `where` applied first
8. ✅ ops: backup `prune` subcommand with `--dry-run`
9. ✅ docs: FAQ entries — vault exclusion, digest dedupe, memory-only 304 cache
10. ✅ examples: json_query group demo over quarantine reasons

## Wave Z status (complete)

1. ✅ kernel: daemon.status() includes quarantine item count and size
2. ✅ brain: /api/adapters ping section carries a checked_at timestamp
3. ✅ memory: recall excludes digest-marker bookkeeping kind by default
4. ✅ security: auth limiter clears expired lockouts on read
5. ✅ interface: telegram /audit gains an --actor filter
6. ✅ interface: dashboard tasks table highlights blocked rows with their blockers
7. ✅ tools: json_query filter coerces booleans (enabled=1 matches true)
8. ✅ ops: backup verify-all --quiet single-line summary
9. ✅ docs: quarantine triage runbook + GET /api/quarantine/{id} inspection endpoint
10. ✅ examples: quarantine triage demo (put → filter → inspect → verdict → delete)

## Wave AA status (complete)

1. ✅ interface: /api/tasks gains an allowlisted status filter
2. ✅ brain: /api/brain lifecycle block carries the daemon start timestamp
3. ✅ memory: remember rejects empty/whitespace text
4. ✅ security: QuarantineStore.stats() (items, bytes, oldest age) reused by daemon.status
5. ✅ interface: telegram /status shows the quarantine item count
6. ✅ interface: dashboard quarantine reasons clickable to toggle the reason filter
7. ✅ tools: json_query mode=unique — distinct values of a key
8. ✅ ops: diskwatch JSON carries bytes_total
9. ✅ docs: ADR-0010 — one guarded path per capability
10. ✅ examples: combined operator drill (backup + quarantine + audit)

## Wave AB status (complete)

1. ✅ kernel: self-check gains a quarantine store + budget sanity line
2. ✅ interface: adapters breaker display shows the tier's last error
3. ✅ memory: recall snippet width parameter, exposed on the recall tool
4. ✅ security: webfetch injection_risk report caps findings at the top 3
5. ✅ interface: telegram /help groups commands by audience
6. ✅ interface: dashboard header shows a quarantine size badge
7. ✅ tools: json_query stats gains a depth-capped nesting summary
8. ✅ ops: backup create reports its retention position (n of keep)
9. ✅ docs: architecture.md capability→guarded-path table
10. ✅ examples: status page demo — daemon.status() rendered offline

## Wave AC status (complete)

1. ✅ kernel: scheduler emits task_started events alongside blocked/released
2. ✅ brain: cache evictions/expired already surfaced in /api/brain snapshot (verified, no change)
3. ✅ memory: episode detail carries step_count alongside the replay
4. ✅ security: promptguard band gauge (0 pass / 1 sanitize / 2 quarantine)
5. ✅ interface: telegram /tasks gains a --limit option (capped at 50)
6. ✅ interface: allowlisted /api/docs/{name} runbook endpoint, linked from the backup panel
7. ✅ tools: json_query filter gains ~= (case-insensitive contains)
8. ✅ ops: preflight gains a backup-freshness check (>24h or empty window)
9. ✅ docs: testing.md — capture pytest exit codes, never pipe blindly
10. ✅ examples: json_query stats+nesting demo over a config blob

## Wave AD status (complete)

1. ✅ kernel: task_started event carries the task source
2. ✅ brain: per-adapter ping opt-out via interface.ping_skip
3. ✅ memory: recall keeps only the best-scoring hit per key
4. ✅ security: quarantine stats gains a top-3 per-reason breakdown
5. ✅ interface: telegram /backup --verify checks the newest archive
6. ✅ interface: adapters card shows probe age + skip badge
7. ✅ tools: json_query mode=pluck; all row modes honor `where`
8. ✅ ops: backup create --verify-immediately (+ retention position)
9. ✅ docs: api.md full endpoint table
10. ✅ examples: combined json drill (stats → filter → sort → pluck → group)

## Wave AE status (complete)

1. ✅ kernel: task_finished event with status + duration
2. ✅ brain: /api/brain budget block exposes the configured daily limit
3. ✅ memory: Memory.rename_key — operator key repair (validated, testable)
4. ✅ security: quarantine reason filter accepts comma-separated needles (OR)
5. ✅ interface: telegram /tasks shows blocked_by inline
6. ✅ interface: adapters card shows live model names from the catalog
7. ✅ tools: json_query filter gains ^= (case-insensitive starts-with)
8. ✅ ops: verify-all reports per-archive duration
9. ✅ docs: tools.md — full json_query mode matrix
10. ✅ examples: operator handoff demo (status, backups, quarantine, audit)

## Wave AF status (complete)

1. ✅ kernel: daemon.stop() publishes daemon_stopping on the lifecycle channel
2. ✅ brain: response cache clear() logs the evicted entry count
3. ✅ memory: consolidation skips whitespace-only goal episodes
4. ✅ security: promptguard scan() accepts a max-findings cap (score stays whole)
5. ✅ interface: telegram /health shows the ok/total check count
6. ✅ interface: quarantine delete needs a second confirming click
7. ✅ tools: json_query mode=help — self-describing filter grammar
8. ✅ ops: diskwatch prints a remediation tip when level is critical
9. ✅ docs: dependency runbook links ADR-0006 and the status filter
10. ✅ examples: json_query operator one-liner cheat sheet demo

## Wave AG status (complete)

1. ✅ kernel: scheduler claims no new tasks once stopping (drain-only tail)
2. ✅ brain: cache snapshot exposes the oldest live entry's age
3. ✅ memory: snippet width contract pinned — markers excluded from the text budget
4. ✅ security: quarantine put rejects whitespace-only content
5. ✅ interface: telegram /blocked gains a --limit option
6. ✅ interface: adapters card truncates last_error with a full-text tooltip
7. ✅ tools: json_query mode=keys — top-level keys with value types
8. ✅ ops: verify-all --quiet names the slowest archive
9. ✅ docs: index.md points to ROADMAP for recent changes
10. ✅ examples: lifecycle demo — daemon_stopping observed by a subscriber

## Wave AH status (complete)

1. ✅ kernel: /api/status uptime grows a humanized field
2. ✅ brain: adapter pings keep a rolling last-5 latency history
3. ✅ memory: snippet width contract pinned (markers excluded)
4. ✅ security: auth limiter snapshot includes configured thresholds
5. ✅ interface: telegram /status adds the cache hit-rate line
6. ✅ interface: task rows carry #task-<id> anchors with highlight
7. ✅ tools: json_query stats carries a sample (first row) for list roots
8. ✅ ops: backup drill --verbose reports the scratch dir path
9. ✅ docs: security.md documents the guard metrics surface
10. ✅ examples: cache demo — put/hit/TTL expiry across a fake clock

## Wave AI backlog (next)

1. kernel: scheduler stats gains `started_at` mirroring the daemon's
2. brain: /api/brain adapters section merges the ping history (recent_ms)
3. memory: recall accepts an explicit `exclude_kinds` complement to kinds
4. security: quarantine release() audits the content length, not the content
5. interface: telegram /skills accepts a name filter argument
6. interface: dashboard backups panel shows the newest archive's verified state when drilled
7. tools: json_query mode=shape honors a caller max_depth
8. ops: preflight --json includes per-check duration_ms
9. docs: operations.md links the backup + quarantine runbooks inline
10. examples: metrics demo — REGISTRY snapshot rendered as text offline

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
