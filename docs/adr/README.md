# Architecture Decision Records

ADRs capture *why* SparkAgent is built the way it is — the choice, the
context, and the consequences. They are immutable once accepted; a new
decision supersedes an old one via a new ADR.

| # | Decision | Status |
|---|---|---|
| [0001](0001-policy-sandbox-with-honest-limits.md) | Policy-level sandbox, honestly labeled | accepted |
| [0002](0002-dual-tier-brain.md) | Dual-tier brain with circuit-broken failover | accepted |
| [0003](0003-openshell-backend-layering.md) | NVIDIA OpenShell as an execution backend tier | accepted |
| 0004 | Per-program working-directory allowlist | drafted |
| 0005 | Adapter-framework migration for Brain clients | proposed |

Format: one file per decision, `NNNN-slug.md`, sections **Context /
Decision / Consequences / Alternatives**.
