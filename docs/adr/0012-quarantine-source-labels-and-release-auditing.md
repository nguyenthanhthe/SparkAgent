# ADR-0012: Quarantine source labels and release auditing

Status: accepted

## Context

Quarantined blobs used to land in the store as anonymous records: the
operator could see *why* something was parked (the reason) but not
*from where* (which surface produced it), and the release audit line
carried only the item id and content length. With multiple surfaces
able to park content (web_fetch today, more later), tracing a
quarantined blob back to its producer meant guesswork.

## Decision

Two additive changes to `security/quarantine.py`:

1. **Source labels.** `QuarantineStore.put()` accepts a `source`
   keyword, stamped on the record (capped at 60 chars, default
   `"unknown"`). Existing callers keep working; `web_fetch` stamps
   itself as `"web_fetch"`. The label rides `list()`/`get()` so
   dashboards and triage tools can group by producer.
2. **Reason in the release audit.** `release()` already published a
   `quarantine.release` audit event with the content *length* only
   (ADR-0010's "content never travels to the audit log" rule). The
   event's detail now also carries the quarantine reason (capped at
   100 chars), so the audit trail answers "why was this parked, and
   what happened to it" without ever exposing the blob.

## Consequences

- **Traceability without exposure.** Producer and verdict travel
  together; the blob itself still never enters the audit log.
- **Additive only.** Records written before the change simply lack the
  `source` key until rewritten; consumers must default on read.
- **Consistent with ADR-0011.** Both decisions extend an auditable
  record with an explicit, bounded field instead of a new status.

## Related

- ADR-0010 (one guarded path per capability), ADR-0011 (approval
  expiry semantics).
- `security/quarantine.py`, `tools/webfetch.py` — implementation.
- Wave AQ items 4 and 6, commits [440/500] and [442/500].
