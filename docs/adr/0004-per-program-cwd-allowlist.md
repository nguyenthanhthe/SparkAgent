# ADR-0004: Per-program working-directory allowlist

Status: accepted (extends ADR-0001's path confinement)

## Context

ADR-0001 confines every path *argument* to the allowed roots, but the
working directory a program *runs from* was unconstrained: an allowlisted
`git` could be invoked from any directory within the sandbox — including
one the operator never intended that tool to touch. On a personal machine
the difference matters: `git` should operate on the operator's repos,
`python` on scratch space, and neither should be launchable from the
other's territory where config files or hooks can influence behavior.

## Decision

Extend `SecurityPolicy` with an optional `program_cwd` map:
`program -> list of allowed working-directory roots`. `SafeExecutor`
resolves the effective cwd (explicit argument, else the sandbox root)
and validates it through `validate_workdir` *inside* the admission
gate, so a violation produces the same audited, blocked `ExecResult`
as any other policy denial — never an uncaught exception. When no
per-program map exists for a program, any allowed root remains
acceptable (default behavior unchanged).

## Consequences

- Blocked-by-cwd spawns return `blocked_reason` and an
  `exec.blocked` audit event, matching the existing denial contract.
- `OpenShellExecutor` inherits the same gate, so sandboxed and
  fallback routes share one admission decision.
- Configuration gains a per-program dimension; empty maps keep
  today's semantics, so no migration is required.
- Cwd confinement is still policy-level, not a chroot — a program
  that changes its own directory at runtime is outside this layer's
  reach (honest-limits stance of ADR-0001).

## Alternatives

- **Global single-workdir rule** — rejected: too coarse; tools
  legitimately need different territories (repos vs scratch).
- **Post-spawn chdir audit** — rejected: detects after the fact;
  the admission gate prevents instead.
- **Per-program argument schemas** — deferred: a larger config
  surface; cwd is the highest-leverage single dimension.
