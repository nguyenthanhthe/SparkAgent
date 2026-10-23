# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[43/500]** commits toward the 500-commit target.

## Waves

| Wave | Theme | Status |
|---|---|---|
| A | Kernel core utilities (errors, async, clock, limits, retry, circuit breaker, metrics, health, correlation, validation) | done |
| B | Security hardening (policy engine, approvals, prompt guard, signatures, quarantine, profiles, process registry, env guard) | done |
| C | Brain adapters (mock/ollama/openai_compat), response cache, cost tracking, context budgeting, tier router | done |
| D | Tool library (calculate, text/json/csv/stats, memory tools, ask_human) + webfetch prompt-guard | done |
| E | Multi-agent swarm (mailbox, orchestrator, consensus, critic, blackboard, topologies) | in progress |
| F | Memory evolution (BM25 hybrid search, graph store, summarizer) | planned |
| G | Interface v3 (OpenAPI spec, CLI REPL, dashboard approvals panel) | planned |
| H | Ops & DevEx (Docker, backup/restore, structured logging, benchmarks) | planned |
| I | Documentation site, examples, tutorials | planned |

Rules: every commit keeps `python -m unittest discover -s tests -t .` green.
