# FAQ

**Is the sandbox a VM?**
No. OpenShell is allowlists + denylists + path confinement + sanitized
environments — policy, not virtualization. An allowlisted `python` runs
with your user's privileges. Run under a non-admin account; keep the
skill approval gate on.

**What happens when Ollama is down?**
The router fails over to the remote tier on the first failure; two
consecutive failures open the circuit for 60s so episodes don't stall on
connection timeouts. When Ollama returns, half-open probes restore it.

**Does it work without a GPU?**
Yes. The local tier reports unhealthy and everything routes to GLM (or
any OpenAI-compatible endpoint). Embeddings fall back to the built-in
hashing embedder.

**Where do API keys live?**
Environment variables or the encrypted vault (`python -m openshell.vault
set GLM_API_KEY`). Never in config files; config examples carry no real
credentials; logs redact known values and key-shaped strings.

**How does the agent avoid prompt injection from web pages?**
Fetched text is scanned (instruction patterns, role spoofing, hidden
unicode, shortener exfil URLs). Moderate risk → wrapped in an explicit
"data, not instructions" fence; high risk → quarantined for operator
review instead of delivered. Heuristics downgrade trust; they are not a
proof.

**Why is my new skill 'pending'?**
Default posture: agent-authored skills need one operator click (web,
Telegram `/approve`, or CLI). Set `tools.skillforge.autonomous: true` to
skip the gate — accepted risk.

**How do I reset everything?**
Stop the daemon, delete `data/` (SQLite, logs, sandbox, quarantine) and
`skills/`. Both regenerate on boot.

**Can two agents share one machine?**
Run second instances with `SPARKAGENT_INTERFACE__WEB__PORT=8789` and a
separate `SPARKAGENT_MEMORY__DB_PATH`; sandboxes and skills directories
follow the project root, so use separate checkouts.

**How big can memory get before recall degrades?**
Recall scans the newest 5000 memories; BM25 indexes them all. Past ~50k
entries, move to a real vector index (the `HybridRanker` vector hook is a
single callable) — the interface won't change.

**Why 500 commits?**
An exercise in atomic, always-green engineering: every feature commit
ships with its tests and keeps `python -m unittest discover -s tests -t .`
passing. See ROADMAP.md.

**Why do backups exclude `vault.bin`?**
The vault blob is master-key-encrypted material — API keys, tokens. A
backup that carries it to another machine defeats the point of the
encryption: whoever gets the archive gets the keys. Keep the vault
separately (password manager, encrypted USB) and test *that* restore
path too. See the backup runbook.

**Why does consolidation skip repeated goals?**
Recurring tasks produce episodes with identical goal text; without the
dedupe, every housekeeping run mints another digest with the same
sentence and recall returns near-duplicates that crowd out distinct
memories. One goal, one digest. The trade-off (an identical goal's
later outcomes are not re-digested) is documented in ADR-0009.

**Why is the web_fetch 304 cache memory-only?**
The validator cache (ETag → last result) is process-local by design:
nothing persists to disk, so a restart revalidates from scratch and
staleness is bounded by the server's own validator semantics, not our
retention. A disk cache would trade a few saved MB for a stale-data
liability that outlives the process. ADR-0008 has the full reasoning.

**Why does my backup show unverified?**
The dashboard backup panel and telegram `/backup` hash-verify the
newest archive on every view. `unverified` means that check failed —
typically a truncated download or a blob that is not a SparkAgent
archive (no manifest). A corrupt newest backup is not restorable; run
`python -m ops.backup create` again and, if it still fails, check the
disk for full-disk errors before trusting any archive in the window.
`--verify`-style full-window checks stay in `python -m ops.backup
verify-all`.

**What happens when an approval expires?**
Nothing runs. Expired requests flip to `status: "expired"` with
`expire_reason: "ttl"` (ADR-0011), stay visible in the
`/pending` queue and `/api/approvals` (so the missed decision is
auditable), and the decision endpoints reject them — re-submit instead
of trying to revive one. The approval gate stays fail-closed: TTL
expiry is a timeout, not a veto override.

**Why are transient failures not counted as failures?**
They are — just in their own bucket. A task whose episode died on
"all LLM tiers failed" is requeued automatically with backoff and lands
in `episodes_failed_transient` (plus the `retries` counter), while
`episodes_failed` only grows for permanent failures (bad plan, crash).
The dashboard scheduler panel shows the split; a high transient number
means your brain tiers are unhealthy, not that the agent planned badly.

**Why do quarantine records carry a source label?**
So triage can answer "where did this come from?" without opening the
blob (ADR-0012). `web_fetch` stamps itself when it parks a page; the
release audit carries the reason, so the trail reads "parked by
web_fetch for prompt-injection risk, released with length N" — and the
content itself still never enters the audit log. Older records simply
say `unknown`.
