# ADR-0011: Approval expiry semantics

Status: accepted

## Context

The approval queue (`security/approval.py`) expires PENDING requests
past their TTL so a stale queue does not accumulate. Before Wave AJ the
expiry transition was silent: the status flipped to `expired`, a
counter incremented, and nothing recorded *why* the request left
PENDING without a decision. An operator inspecting a queue days later
could not distinguish "the operator denied this" from "nobody looked at
it in time" — and dashboards had no field to show that difference.

## Decision

The expiry transition now stamps an explicit reason on the request:

1. `Request.expire_reason` is set to `"ttl"` whenever the queue moves a
   request from PENDING to EXPIRED (both the lazy `_get_fresh` path and
   the sweep `_expire_all`).
2. `request_to_dict()` surfaces `expire_reason` in every serialized
   payload (`/api/status`, `/api/approvals`, telegram `/pending`).
3. Decision paths (`approve`/`deny`) never set the field — it stays
   `None` for any request that received a human decision, so the
   payload shape is uniform and the absence of a decision is visible
   by `status == "expired"` paired with `expire_reason == "ttl"`.

## Consequences

- **Auditable staleness.** The queue's failure mode ("nothing was
  decided in time") is now a first-class, serialized fact instead of an
  inference from a bare status string.
- **No new persistence.** The reason rides the existing in-memory
  request record; no schema change was needed.
- **Extensible reasons.** Future transitions (e.g. superseded by a
  newer request, withdrawn by the requester) can add new reason values
  without another status enum entry.

## Related

- ADR-0010 (one guarded path per capability) — expiry keeps the
  approval gate's single decision surface intact.
- `security/approval.py` — implementation.
- Wave AJ item 4, commit [362/500].
