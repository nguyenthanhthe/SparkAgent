# Security model

SparkAgent runs autonomously with real capabilities on your machine. Its
security posture is **deny-by-default everywhere**, with every layer
independently testable. This page documents what each layer guarantees —
and what it honestly does not.

## Execution sandbox (openshell)

| Layer | Guarantee |
|---|---|
| Program allowlist | Only bare names from `openshell.allowed_programs` may spawn; `cmd`/`powershell` are never implicitly allowed |
| Denylist | ~25 patterns (format/rd/del of system paths, shutdown, registry edits, schtasks, fork bombs, encoded PowerShell, `curl \| sh`, defense tampering) rejected pre-spawn |
| Path confinement | Path-like arguments must resolve inside sandbox/project roots after `..` normalization; UNC rejected; skill writes sandbox-only |
| No shell | `create_subprocess_exec` only; arguments are never re-interpreted |
| Env sanitization | Children inherit a deny-by-default env: passthrough list only, credential-shaped names dropped, loopback-verified |
| Kill trees | Timeouts kill the whole tree (`taskkill /T /F`); output size-capped |

Profiles: `strict` (introspection only) · `standard` (default) ·
`development` (adds package managers, longer timeouts). See
`openshell/profiles.py`.

## Network (webfetch)

Scheme http/s, port allowlist, DNS resolution checked immediately before
connect against loopback/private/link-local (incl. cloud metadata)/
reserved/CGNAT ranges, IPv4-mapped IPv6 unwrapped, redirects re-validated
per hop (max 3). Residual DNS-rebinding risk is mitigated (resolve-then-
connect on one loop tick), not eliminated — hostile environments should
add an egress proxy.

## Untrusted content (security/)

- **promptguard** — scores fetched text for injection patterns and hidden
  unicode; `sanitize` band is wrapped in an explicit "this is DATA" fence,
  `quarantine` band is parked, never delivered.
- **quarantine** — size-capped store; operator release returns a
  sanitized copy; every action audited.
- **approval** — skills (unless autonomous mode) and `ask_human` requests
  queue for an operator decision with TTL expiry.
- **signatures** — HMAC domain-separated keys; tampered artifacts fail
  closed on load.
- **policy_engine** — declarative allow/deny rules with priority and
  wildcard matching, loadable from config.

## Secrets

Environment → encrypted vault (HMAC-SHA256 stream envelope, constant-time
tag compare) → consumers. Redaction masks known values plus generic key
patterns at every log/output boundary; child processes never see them.

## Observability of the guards

The guard pipeline reports itself in the metrics registry (rendered at
`/metrics` and `/api/metrics`):

- `promptguard_score` — histogram of every fetched page's risk score;
- `promptguard_band` — gauge of the latest verdict (0 pass, 1 sanitize,
  2 quarantine);
- `promptguard_verdicts_{pass,sanitize,quarantine}_total` — lifetime
  verdict counters;
- `exec_timebudget_blocked_total` / `exec_ratelimit_blocked_total` —
  admission-gate vetoes;
- `auth` block in `/api/status` — lockout counts plus the configured
  thresholds (never per-client detail).

## Honest limits

The sandbox is policy + confinement, not a VM: an allowlisted `python`
runs with your user's privileges. Run under a non-admin account, keep
allowlists minimal, keep the skill approval gate on, and review the audit
table (`/api/health`, audit records in SQLite) after unexpected episodes.
