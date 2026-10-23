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
