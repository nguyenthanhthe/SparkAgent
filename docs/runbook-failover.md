# Runbook: GPU tier failover

What to do when the local (Tier 1) GPU brain degrades or dies, and how
to read the signals that say so. This is an operator runbook — the
failover itself is automatic; this document is for when it isn't.

## How the tiers behave

- Routing order is **local → remote** (`brain.fallback_after_failures`,
  default 2 consecutive failures put a tier in a 60s cooldown; remote is
  skipped while the daily spend budget is exhausted).
- The remote tier needs `GLM_API_KEY` in the vault/environment; if it is
  missing, all-tiers-down ends as `BrainUnavailable` with per-tier errors.
- A VRAM resource guard can veto the local tier per request
  (daemon-wired). Cooldowns, guards, and per-tier stats are visible in
  `GET /api/brain → health` and on the dashboard Brain card.
- Streaming (`chat_stream`) fails over only **before the first chunk**;
  a mid-stream failure propagates rather than silently restarting.

## Symptoms → actions

| Signal | Meaning | Action |
|---|---|---|
| `local: cooldown after N failures (last: ...)` in /api/brain | Ollama daemon down or model erroring | `ollama list` — is the model pulled? `ollama ps` — is it loaded? Restart the daemon if unresponsive. |
| `resource guard: not enough free VRAM` | VRAM occupied by another process | Close the offender, or lower `brain.local.num_ctx` in config; the agent runs remote-only meanwhile (costs money). |
| `remote: GLM_API_KEY not set or disabled` | remote tier unconfigured | Set the key via the vault; without it a dead local tier means a dead agent. |
| `daily spend budget exhausted` | budget guard paused remote | Raise the budget in config, or fix the local tier; remote stays paused until the day rolls over otherwise. |
| `BrainUnavailable` in logs, both tiers listed | both tiers failed | Fix either tier; the error message lists each tier's last error — start there. |

## Verification after intervention

1. `GET /api/health` — memory + brain checks report ok.
2. `GET /api/brain → stats.local.consecutive_failures` — should be 0
   after the next successful chat (cooldown clears on success).
3. Submit a trivial task from the dashboard; watch the Live log panel —
   `exec` and brain errors appear there within seconds.

## Cost note

While the local tier is down, every chat runs on the remote tier. The
spend panel (dashboard) and `costs.today_usd` in /api/brain show the
rate; the budget guard caps the damage automatically.
