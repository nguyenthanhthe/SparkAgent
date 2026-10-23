# Brain — providers, routing, economics

## Adapters

Every provider implements one protocol (`brain/adapters/base.py`):
`chat(messages, *, temperature, max_tokens, json_mode)` →
`AdapterResponse(text, model, usage…)`, plus `healthy()` and `close()`.

| name | provider | notes |
|---|---|---|
| `ollama` | local GPU (Nemotron, Llama…) | /api/chat, keep_alive, num_ctx, `format=json` mode |
| `openai_compat` | GLM, OpenAI, vLLM, LM Studio, LiteLLM | one client; key from vault/env only; 429/5xx retry with equal-jitter backoff; 401 fails fast; pluggable transport for offline tests |
| `mock` | deterministic | scriptable queue or stable hash of the prompt; powers the test suite |

Register new providers with `adapter_registry.register(name, factory)`.

## Router

`TierRouter` orders tiers by priority and tries the first admissible one:

- per-tier **circuit breaker** (5 failures → open 60s → half-open probes)
- **health cache** (30s TTL) — one probe, not one per request
- **veto hooks** — the daemon wires the VRAM guard here: <1024 MB free ⇒
  skip the local tier this tick
- **response cache** — identical (model, messages, params) hits the LRU
  within TTL; cache hits cost nothing and count in `saved_tokens`
- **cost tracking** — every response records tokens × pattern price table
  into per-model/tier/day ledgers; `within_budget(daily_usd)` gates spend

## Context budgeting

`ContextBudget(window, reserve_output)` fits prompt parts under a token
estimate (chars/4 + per-message overhead): trim shrinkable parts (lowest
priority first, 25% floor), then drop, never touching the system contract
or goal. `summarize_scratchpad` compresses old ReAct turns into one note
when episodes run long.

## Cost model

Prices are USD/1M tokens by model pattern (`glm-5.3*`, `gpt-4o*`,
`nemotron*` = 0 local …). Local GPU inference is priced at zero — the
ledger still counts tokens, so routing decisions can weigh latency vs
cost with real numbers. Override prices via `CostTracker(prices=[…])`.
