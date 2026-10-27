# ADR-0010: One guarded path per capability

Status: accepted

## Context

SparkAgent exposes the same capability through several doors: an agent
tool (the ReAct loop drives it), an HTTP endpoint (dashboard and
operators), a CLI subcommand (operators and cron), and sometimes a
Telegram command (remote operators). Every extra door is a chance for
the copies to drift: one gets the SSRF guard, one doesn't; one audits,
one forgets; a fix lands in the tool but not the endpoint.

Incidents this rule prevents were already visible by Wave S: the
`sqlite` CLI, the `sqlite_query` tool, and `/api/db` initially grew as
three look-alike code paths before they converged on one `lookup()`.

## Decision

Each capability gets exactly **one guarded implementation**, and every
surface is a thin adapter over it:

- **Read-only database lookups** — `tools/sqlite_query.lookup()`;
  the tool, `/api/db`, and the CLI `sqlite` command all call it.
- **Backup lifecycle** — `ops/backup.py` functions (`create_backup`,
  `verify_backup`, `restore_backup`, `restore_drill`, `list_backups`,
  `prune_backups`); the CLI, `/api/backup`, and the Telegram `/backup`
  command are views over the same functions. The dashboard listing and
  chat listing can never disagree about what a backup is.
- **Quarantine** — `security/quarantine.QuarantineStore`; the web
  actions, the runbook flows, and `daemon.status()` statistics all go
  through the store, which owns the budget and TTL invariants.
- **Auth** — `security/auth_limiter.AuthRateLimiter`; the middleware is
  the only place tokens are checked, and `/api/status` reports its
  aggregate snapshot rather than reimplementing counting.

Guards live inside the guarded implementation, not in the adapters:
SSRF validation inside `WebFetcher.fetch`, static-statement discipline
inside `lookup`, hash verification inside `restore_backup`. A new door
(cost: a route registration, a command parse) inherits the guards for
free; making a door that *skips* a guard requires deliberately
bypassing the implementation, which stands out in review.

## Consequences

- Tests target the guarded implementation once; endpoint tests then
  only assert wiring (status codes, shapes), not behavior copies.
- Surfaces can have different convenience (defaults, output formats)
  but never different *authority*: nothing a CLI can do to the data dir
  is forbidden to the endpoint, and vice versa — differing authority
  would mean a second implementation is hiding somewhere.
- Some indirection cost: adapters must expose the union of parameters
  callers need (`lookup` grew `order_by`/`descending` for the endpoint).
  The union is bounded by the capability, not by the number of doors.
- Telegram commands and web endpoints stay stateless views; anything
  stateful (lockout tracking, manifests) lives below them.

## Alternatives

- **Per-surface implementations with shared lint checks** — rejected:
  lints catch style drift, not a missing audit row or an unvalidated
  redirect.
- **One god-adapter that proxies every capability generically** —
  rejected: the security properties are capability-specific (hash
  verification means nothing for recall); a generic layer would blur
  them.
- **Capability-per-surface feature flags** — rejected: disabling a
  surface should be deployment config, never a divergent code path.
