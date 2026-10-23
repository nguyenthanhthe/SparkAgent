# ADR-0001: Policy-level sandbox, honestly labeled

Status: accepted (supersedes none; partially extended by ADR-0003)

## Context

SparkAgent executes model-chosen commands on a personal Windows machine.
Full VM/container isolation per command is heavyweight locally, yet
unbounded execution is unacceptable. Pre-existing "agent frameworks"
often ran shell strings directly — the exact failure mode we needed to
preclude.

## Decision

Build the sandbox as *policy layers* — program allowlist, dangerous-
pattern denylist, path confinement after `..` normalization, no shell
(`create_subprocess_exec` only), sanitized child environments, output
caps, kill trees — and **document explicitly that this is not a VM**.
An allowlisted `python` still runs with the user's privileges; the
mitigation is running under a non-admin account and keeping allowlists
minimal.

## Consequences

- Zero external sandbox dependencies; works on stock Windows/Linux.
- Every layer is unit-testable offline (the suite's tamper/blocked
  cases live here).
- Users who need kernel-grade confinement now layer NVIDIA OpenShell
  on top (ADR-0003) — the policy layer stays as the first gate.
- Any new capability that touches the machine must route through the
  executor; this is enforced by review convention, not the type system.

## Alternatives

- **A VM per command** — rejected: startup latency and local resource
  cost dwarf typical tool calls; revisited via OpenShell sandboxes.
- **Pure prompt-level safety** ("ask the model nicely") — rejected:
  not a boundary at all.
- **OS job objects/AppContainer-only** — deferred: platform-specific
  depth without the portability the policy layer gives.
