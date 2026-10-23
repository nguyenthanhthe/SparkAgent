# ADR-0002: Dual-tier brain with circuit-broken failover

Status: accepted

## Context

The agent must keep working 24/7 across two very different LLM tiers:
a local GPU tier (Nemotron via Ollama — free, private, occasionally
down or VRAM-starved on a laptop) and a remote OpenAI-compatible tier
(GLM — reliable, metered, needs an API key). A naive try-order either
stalls episodes on a dead local daemon or wastes remote budget when
local would do.

## Decision

Try tiers in declared order with per-tier state machines: consecutive-
failure counters, a 60 s cooldown after N failures, health-probe
caching (30 s TTL), a VRAM guard veto for the local tier, and a daily
spend-budget veto for the remote tier. Any tier exception fails over
instead of crashing the episode; both guards fail *open* (a broken
guard never blocks chat).

## Consequences

- Episodes degrade gracefully: local down → remote; budget out →
  local-only; both out → a clear `BrainUnavailable` naming each tier.
- Tier health and cost are observable per request (dashboard, /api/brain,
  Prometheus metrics).
- The bridge retains its own client classes even though an adapter
  framework exists (ADR-0005 tracks migrating them); duplication is
  accepted until then to avoid destabilizing the always-green suite.

## Alternatives

- **Single tier** — rejected: loses privacy or reliability outright.
- **Complexity-aware routing (quality/latency/cost scoring)** — deferred
  until real per-tier latency data accumulates in the metrics histograms.
- **Round-robin load balancing** — rejected: hides failures instead of
  failing over.
