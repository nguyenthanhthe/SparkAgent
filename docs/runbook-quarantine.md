# Runbook: quarantine triage

What to do when the prompt guard parks content: how to read the
quarantine, decide release vs delete, and keep the audit trail honest.

## How content lands in quarantine

- A `web_fetch` body scores in the promptguard *quarantine* band
  (injection patterns, hidden unicode, role-spoofing — see
  `security/promptguard.py` for the scoring bands). The fetch returns a
  `[BLOCKED]` notice to the agent; the raw body waits on disk.
- The item's meta carries the source URL and the guard score, so the
  listing answers "where did this come from?" without opening it.

## Triage flow

```bash
# 1. list — newest first; narrow with ?reason= for one kind
curl -s 'http://127.0.0.1:8788/api/quarantine' | python -m json.tool
curl -s 'http://127.0.0.1:8788/api/quarantine?reason=prompt-injection'

# 2. inspect one item (id from the listing)
#    GET /api/quarantine/{id} returns {record, content}

# 3a. release (audited) — content is sanitized on the way out
curl -s -X POST 'http://127.0.0.1:8788/api/quarantine/{id}/release'

# 3a'. or restore (two-step): submit an approval request, then release
# once an operator has approved it — for when you want a second pair
# of eyes before content touches the model again
curl -s -X POST 'http://127.0.0.1:8788/api/quarantine/{id}/restore'

# 3b. or delete (also audited)
curl -s -X POST 'http://127.0.0.1:8788/api/quarantine/{id}/delete'
```

From chat: the audit trail around a quarantine decision is visible via
`/audit --actor operator` in Telegram.

## Release vs delete

| Situation | Action |
|---|---|
| False positive (docs page that quotes injection examples) | release — the sanitizer fences it as untrusted data on the way out |
| Genuine injection attempt from a hostile site | delete; the source URL in meta tells you what to block or stop fetching |
| You cannot tell | delete — the fetch can be repeated if it matters, quarantine TTL (7 days) deletes it anyway |
| Recurring false positives from one source | delete AND stop fetching that source; do not train yourself to auto-release |

## Verification after triage

1. `GET /api/quarantine` no longer lists the item.
2. `GET /api/audit?limit=20` shows the `quarantine.release` or delete
   row with your decision.
3. `GET /api/status → quarantine` item count matches what the listing
   shows — drift means something wrote around the store.

## Notes

- Quarantine is bounded (16 MB total, 7-day TTL); housekeeping deletes
  expired items, so triage "later" has a deadline.
- Released content passes through `promptguard.sanitize` — it is
  wrapped as untrusted data, not trusted raw. Release ≠ trust.
