# SparkAgent documentation

An autonomous 24/7 local AI agent kernel: ReAct core, OpenShell sandbox,
dual-tier brain (Nemotron/CUDA + GLM fallback), self-authoring skills,
swarm coordination, and hybrid memory.

| Page | Contents |
|---|---|
| [Architecture](architecture.md) | layers, supervision, invariants |
| [OpenShell integration](openshell-integration.md) | NVIDIA OpenShell sandbox backend, policy export |
| [Security](security.md) | sandbox, guards, secrets, honest limits |
| [Tools](tools.md) | built-in tools, SkillForge sandbox contract |
| [Brain](brain.md) | adapters, tier routing, cache, cost model |
| [Memory](memory.md) | hybrid recall, consolidation, entity graph |
| [Swarm](swarm.md) | roles, topologies, consensus |
| [Topology catalog](topologies.md) | the five composition shapes with mermaid diagrams |
| [Operations](operations.md) | services, Docker, monitoring, backups |
| [Failover runbook](runbook-failover.md) | GPU tier failover: signals, actions, verification |
| [Dependency runbook](runbook-dependencies.md) | task chains: blocked semantics, manual release, failures |
| [Backup runbook](runbook-backups.md) | monthly drill: create, tag, verify-all, scratch restore |
| [Quarantine runbook](runbook-quarantine.md) | triage: list, filter by reason, release vs delete |
| [API](api.md) | HTTP endpoints, auth, CLI |
| [FAQ](faq.md) | common questions |

Start with the [README](../README.md) quickstart; run
`python main.py --check` to verify your install offline.
