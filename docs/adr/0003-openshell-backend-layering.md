# ADR-0003: NVIDIA OpenShell as an execution backend tier

Status: accepted

## Context

ADR-0001 left an honest gap: policy guardrails are not kernel
confinement. NVIDIA OpenShell (Apache-2.0) provides exactly that —
kernel-confined sandboxes, policy-governed filesystem/syscall/network
access, credential injection only at approved endpoints — but is a
separate runtime that may or may not be installed on a given machine,
and its Windows support is WSL2-experimental.

## Decision

Make the executor layered and optional: `OpenShellExecutor` subclasses
the policy executor and, **after** our policy admission (allowlist,
denylist, paths, rate limits) passes, routes the spawn through
`openshell sandbox exec --sandbox <name> -- <exe> <args...>`. Backend
selection is config-driven (`auto` default: probe once, sandbox when
present, transparent fallback otherwise). Additionally,
`policy_translate.py` exports our rules as a *draft* OpenShell sandbox
policy — applied only through OpenShell's own review flow; SparkAgent
never installs policies silently.

## Consequences

- Same code path everywhere; enforcement strength follows whatever
  runtime the host has.
- Our policy layer remains the first gate, so a SparkAgent
  misconfiguration can never widen sandbox permissions (defense in
  depth in the strict direction).
- Sandbox routing is unit-tested with injected fakes (no runtime
  needed); live behavior depends on OpenShell's CLI contract, pinned
  by a minimum-version gate and re-verified on probe.
- The `describe_backend()` status gives operators live visibility of
  which tier actually ran their commands.

## Alternatives

- **Depend on OpenShell unconditionally** — rejected: breaks stock
  Windows hosts and the zero-dependency property.
- **Implement our own seccomp/AppContainer enforcement** — rejected:
  platform-specific, high blast radius; the runtime already exists.
- **Policy export only (no exec routing)** — rejected as the sole
  option: exec routing is what makes the upgrade real for the agent.
