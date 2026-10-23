# SparkAgent v2 — Enterprise Evolution Roadmap

Goal: evolve the v1 kernel into a world-class autonomous agent framework.
Progress counter: **[10/500]** commits toward the 500-commit target.

## Waves

| Wave | Theme | Status |
|---|---|---|
| A | Kernel core utilities (errors, async, clock, limits, retry, circuit breaker, metrics, health, correlation, validation) | in progress |
| B | Security hardening (policy engine, approval workflow, prompt-injection guard, code signing, quarantine, sandbox profiles, process registry) | planned |
| C | Brain adapters (OpenAI/Anthropic/llama.cpp/vLLM/mock), smart router, token budgets, response cache, cost tracking | planned |
| D | Tool library expansion (fs, calculator, JSON/CSV/stats, notes, search, ask-human, code analysis) | planned |
| E | Multi-agent swarm (mailbox, orchestrator, consensus, critic, blackboard, topologies) | planned |
| F | Memory evolution (BM25 hybrid search, graph store, summarizer, forgetting curve) | planned |
| G | Interface v2 (versioned API, OpenAPI spec, Prometheus metrics, WebSocket, CLI REPL) | planned |
| H | Ops & DevEx (Docker, service wrappers, backup/restore, structured logging, benchmarks) | planned |
| I | Documentation site, examples, tutorials | planned |

Rules: every commit keeps `python -m unittest discover -s tests -t .` green.
