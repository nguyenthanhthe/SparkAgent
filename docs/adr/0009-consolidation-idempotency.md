# ADR-0009: Digest dedupe and consolidation idempotency

Status: accepted

## Context

Episode consolidation distills finished episodes into compact digest
memories during housekeeping. Two forces make naive consolidation
non-idempotent:

- **Re-runs.** The digest-marker row (`kind=digest-marker`,
  `key=episode:<id>`) is written *after* the digest. A crash between
  the digest write and the marker write would re-digest the same
  episode on the next sweep.
- **Repeated goals.** Recurring tasks and retried one-shots produce
  episodes whose goal text is identical. Each sweep would mint a new
  digest containing the same sentence, and recall would return
  near-duplicate digests that crowd out distinct memories.

## Decision

Consolidation is made idempotent by two guards, checked before any
digest is written:

1. **Marker guard (exact id):** `episodes_without_digest()` already
   excludes episodes having a `digest-marker` row keyed on their id —
   this closes the re-run window.
2. **Goal guard (text):** `_consolidate_episodes` loads all
   `digest-marker` texts via `Memory.digest_markers()`, normalizes
   the `[digested] <goal>` payload (strip + lowercase), and skips any
   candidate episode whose normalized goal is already in that set.
   Duplicate goals within one batch are not possible after the set
   check (first occurrence wins).

The `[digested] <goal>` marker text doubles as the dedupe index — no
separate structure, no migration, and the marker remains a plain
memory that recall can ignore (its kind excludes it from normal
surfaces).

## Consequences

- Repeated housekeeping runs converge: the second run digests nothing
  (`_consolidate_episodes` returns 0), so digest memories never grow
  from re-runs.
- A recurring task's hundredth run leaves one digest from its first —
  the trade-off is that *changes* in outcome for an identical goal are
  not re-digested. The episode rows (and their tags) remain the
  detailed record until retention prunes them.
- The goal comparison is exact-normalized text, not semantic: "check
  disk" and "check the disk" are different keys. This is deliberate —
  fuzzy dedupe risks silently dropping genuinely distinct digests, and
  a false negative (extra digest) is cheap while a false positive
  (missing digest) is not.
- Consolidation also seeds the entity graph from digest texts
  (`source=consolidation`); the graph's own triple dedupe keeps
  idempotent re-seeding harmless if a digest is ever reprocessed.

## Alternatives

- **Dedupe digests by content hash of the digest text** — rejected:
  two different goals can summarize to the same sentence, and the
  marker-based goal key is available earlier (before summarizing).
- **Semantic (embedding) similarity dedupe** — rejected for now: the
  false-positive risk drops recall trustworthiness, and the embedding
  cost in a housekeeping path is not justified while goals repeat
  verbatim.
- **Delete the source episodes immediately after digesting** —
  rejected: episodes are the audit trail for what the agent actually
  did; retention prunes them on schedule instead.
